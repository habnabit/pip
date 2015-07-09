import os
import shutil
import sys
import tempfile

import pytest

from mock import Mock, patch, mock_open
from pip.exceptions import (PreviousBuildDirError, InvalidWheelFilename,
                            UnsupportedWheel)
from pip.download import PipSession
from pip.index import PackageFinder
from pip.req import (InstallRequirement, RequirementSet, Requirements)
from pip.req.req_install import parse_editable
from pip.utils import read_text_file
from pip._vendor import pkg_resources
from tests.lib import assert_raises_regexp


class TestRequirementSet(object):
    """RequirementSet tests"""

    def setup(self):
        self.tempdir = tempfile.mkdtemp()

    def teardown(self):
        shutil.rmtree(self.tempdir, ignore_errors=True)

    def basic_reqset(self):
        return RequirementSet(
            build_dir=os.path.join(self.tempdir, 'build'),
            src_dir=os.path.join(self.tempdir, 'src'),
            download_dir=None,
            session=PipSession(),
        )

    def test_no_reuse_existing_build_dir(self, data):
        """Test prepare_files raise exception with previous build dir"""

        build_dir = os.path.join(self.tempdir, 'build', 'simple')
        os.makedirs(build_dir)
        open(os.path.join(build_dir, "setup.py"), 'w')
        reqset = self.basic_reqset()
        req = InstallRequirement.from_line('simple')
        reqset.add_requirement(req)
        finder = PackageFinder([data.find_links], [], session=PipSession())
        assert_raises_regexp(
            PreviousBuildDirError,
            "pip can't proceed with [\s\S]*%s[\s\S]*%s" %
            (req, build_dir.replace('\\', '\\\\')),
            reqset.prepare_files,
            finder,
        )

    def test_environment_marker_extras(self, data):
        """
        Test that the environment marker extras are used with
        non-wheel installs.
        """
        reqset = self.basic_reqset()
        req = InstallRequirement.from_editable(
            data.packages.join("LocalEnvironMarker"))
        reqset.add_requirement(req)
        finder = PackageFinder([data.find_links], [], session=PipSession())
        reqset.prepare_files(finder)
        # This is hacky but does test both case in py2 and py3
        if sys.version_info[:2] in ((2, 7), (3, 4)):
            assert reqset.has_requirement('simple')
        else:
            assert not reqset.has_requirement('simple')


@pytest.mark.parametrize(('file_contents', 'expected'), [
    (b'\xf6\x80', b'\xc3\xb6\xe2\x82\xac'),  # cp1252
    (b'\xc3\xb6\xe2\x82\xac', b'\xc3\xb6\xe2\x82\xac'),  # utf-8
    (b'\xc3\xb6\xe2', b'\xc3\x83\xc2\xb6\xc3\xa2'),  # Garbage
])
def test_egg_info_data(file_contents, expected):
    om = mock_open(read_data=file_contents)
    em = Mock()
    em.return_value = 'cp1252'
    with patch('pip.utils.open', om, create=True):
        with patch('locale.getpreferredencoding', em):
            ret = read_text_file('foo')
    assert ret == expected.decode('utf-8')


class TestInstallRequirement(object):

    def test_url_with_query(self):
        """InstallRequirement should strip the fragment, but not the query."""
        url = 'http://foo.com/?p=bar.git;a=snapshot;h=v0.1;sf=tgz'
        fragment = '#egg=bar'
        req = InstallRequirement.from_line(url + fragment)
        assert req.link.url == url + fragment, req.link

    def test_unsupported_wheel_requirement_raises(self):
        with pytest.raises(UnsupportedWheel):
            InstallRequirement.from_line(
                'peppercorn-0.4-py2.py3-bogus-any.whl',
            )

    def test_installed_version_not_installed(self):
        req = InstallRequirement.from_line('simple-0.1-py2.py3-none-any.whl')
        assert req.installed_version is None

    def test_str(self):
        req = InstallRequirement.from_line('simple==0.1')
        assert str(req) == 'simple==0.1'

    def test_repr(self):
        req = InstallRequirement.from_line('simple==0.1')
        assert repr(req) == (
            '<InstallRequirement object: simple==0.1 editable=False>'
        )

    def test_invalid_wheel_requirement_raises(self):
        with pytest.raises(InvalidWheelFilename):
            InstallRequirement.from_line('invalid.whl')

    def test_wheel_requirement_sets_req_attribute(self):
        req = InstallRequirement.from_line('simple-0.1-py2.py3-none-any.whl')
        assert req.req == pkg_resources.Requirement.parse('simple==0.1')

    def test_url_preserved_line_req(self):
        """Confirm the url is preserved in a non-editable requirement"""
        url = 'git+http://foo.com@ref#egg=foo'
        req = InstallRequirement.from_line(url)
        assert req.link.url == url

    def test_url_preserved_editable_req(self):
        """Confirm the url is preserved in a editable requirement"""
        url = 'git+http://foo.com@ref#egg=foo'
        req = InstallRequirement.from_editable(url)
        assert req.link.url == url

    def test_get_dist(self):
        req = InstallRequirement.from_line('foo')
        req.egg_info_path = Mock(return_value='/path/to/foo.egg-info')
        dist = req.get_dist()
        assert isinstance(dist, pkg_resources.Distribution)
        assert dist.project_name == 'foo'
        assert dist.location == '/path/to'

    def test_get_dist_trailing_slash(self):
        # Tests issue fixed by https://github.com/pypa/pip/pull/2530
        req = InstallRequirement.from_line('foo')
        req.egg_info_path = Mock(return_value='/path/to/foo.egg-info/')
        dist = req.get_dist()
        assert isinstance(dist, pkg_resources.Distribution)
        assert dist.project_name == 'foo'
        assert dist.location == '/path/to'

    def test_markers(self):
        for line in (
            # recommanded syntax
            'mock3; python_version >= "3"',
            # with more spaces
            'mock3 ; python_version >= "3" ',
            # without spaces
            'mock3;python_version >= "3"',
        ):
            req = InstallRequirement.from_line(line)
            assert req.req.project_name == 'mock3'
            assert req.req.specs == []
            assert req.markers == 'python_version >= "3"'

    def test_markers_semicolon(self):
        # check that the markers can contain a semicolon
        req = InstallRequirement.from_line('semicolon; os_name == "a; b"')
        assert req.req.project_name == 'semicolon'
        assert req.req.specs == []
        assert req.markers == 'os_name == "a; b"'

    def test_markers_url(self):
        # test "URL; markers" syntax
        url = 'http://foo.com/?p=bar.git;a=snapshot;h=v0.1;sf=tgz'
        line = '%s; python_version >= "3"' % url
        req = InstallRequirement.from_line(line)
        assert req.link.url == url, req.link
        assert req.markers == 'python_version >= "3"'

        # without space, markers are part of the URL
        url = 'http://foo.com/?p=bar.git;a=snapshot;h=v0.1;sf=tgz'
        line = '%s;python_version >= "3"' % url
        req = InstallRequirement.from_line(line)
        assert req.link.url == line, req.link
        assert req.markers is None

    def test_markers_match(self):
        # match
        for markers in (
            'python_version >= "1.0"',
            'sys_platform == %r' % sys.platform,
        ):
            line = 'name; ' + markers
            req = InstallRequirement.from_line(line)
            assert req.markers == markers
            assert req.match_markers()

        # don't match
        for markers in (
            'python_version >= "5.0"',
            'sys_platform != %r' % sys.platform,
        ):
            line = 'name; ' + markers
            req = InstallRequirement.from_line(line)
            assert req.markers == markers
            assert not req.match_markers()

    def test_extras_for_line_path_requirement(self):
        line = 'SomeProject[ex1,ex2]'
        filename = 'filename'
        comes_from = '-r %s (line %s)' % (filename, 1)
        req = InstallRequirement.from_line(line, comes_from=comes_from)
        assert len(req.extras) == 2
        assert req.extras[0] == 'ex1'
        assert req.extras[1] == 'ex2'

    def test_extras_for_line_url_requirement(self):
        line = 'git+https://url#egg=SomeProject[ex1,ex2]'
        filename = 'filename'
        comes_from = '-r %s (line %s)' % (filename, 1)
        req = InstallRequirement.from_line(line, comes_from=comes_from)
        assert len(req.extras) == 2
        assert req.extras[0] == 'ex1'
        assert req.extras[1] == 'ex2'

    def test_extras_for_editable_path_requirement(self):
        url = '.[ex1,ex2]'
        filename = 'filename'
        comes_from = '-r %s (line %s)' % (filename, 1)
        req = InstallRequirement.from_editable(url, comes_from=comes_from)
        assert len(req.extras) == 2
        assert req.extras[0] == 'ex1'
        assert req.extras[1] == 'ex2'

    def test_extras_for_editable_url_requirement(self):
        url = 'git+https://url#egg=SomeProject[ex1,ex2]'
        filename = 'filename'
        comes_from = '-r %s (line %s)' % (filename, 1)
        req = InstallRequirement.from_editable(url, comes_from=comes_from)
        assert len(req.extras) == 2
        assert req.extras[0] == 'ex1'
        assert req.extras[1] == 'ex2'


def test_requirements_data_structure_keeps_order():
    requirements = Requirements()
    requirements['pip'] = 'pip'
    requirements['nose'] = 'nose'
    requirements['coverage'] = 'coverage'

    assert ['pip', 'nose', 'coverage'] == list(requirements.values())
    assert ['pip', 'nose', 'coverage'] == list(requirements.keys())


def test_requirements_data_structure_implements__repr__():
    requirements = Requirements()
    requirements['pip'] = 'pip'
    requirements['nose'] = 'nose'

    assert "Requirements({'pip': 'pip', 'nose': 'nose'})" == repr(requirements)


def test_requirements_data_structure_implements__contains__():
    requirements = Requirements()
    requirements['pip'] = 'pip'

    assert 'pip' in requirements
    assert 'nose' not in requirements


@patch('os.path.normcase')
@patch('pip.req.req_install.os.getcwd')
@patch('pip.req.req_install.os.path.exists')
@patch('pip.req.req_install.os.path.isdir')
def test_parse_editable_local(
        isdir_mock, exists_mock, getcwd_mock, normcase_mock):
    exists_mock.return_value = isdir_mock.return_value = True
    # mocks needed to support path operations on windows tests
    normcase_mock.return_value = getcwd_mock.return_value = "/some/path"
    assert parse_editable('.', 'git') == (None, 'file:///some/path', None, {})
    normcase_mock.return_value = "/some/path/foo"
    assert parse_editable('foo', 'git') == (
        None, 'file:///some/path/foo', None, {},
    )


def test_parse_editable_default_vcs():
    assert parse_editable('https://foo#egg=foo', 'git') == (
        'foo',
        'git+https://foo#egg=foo',
        None,
        {'egg': 'foo'},
    )


def test_parse_editable_explicit_vcs():
    assert parse_editable('svn+https://foo#egg=foo', 'git') == (
        'foo',
        'svn+https://foo#egg=foo',
        None,
        {'egg': 'foo'},
    )


def test_parse_editable_vcs_extras():
    assert parse_editable('svn+https://foo#egg=foo[extras]', 'git') == (
        'foo[extras]',
        'svn+https://foo#egg=foo[extras]',
        None,
        {'egg': 'foo[extras]'},
    )


@patch('os.path.normcase')
@patch('pip.req.req_install.os.getcwd')
@patch('pip.req.req_install.os.path.exists')
@patch('pip.req.req_install.os.path.isdir')
def test_parse_editable_local_extras(
        isdir_mock, exists_mock, getcwd_mock, normcase_mock):
    exists_mock.return_value = isdir_mock.return_value = True
    normcase_mock.return_value = getcwd_mock.return_value = "/some/path"
    assert parse_editable('.[extras]', 'git') == (
        None, 'file://' + "/some/path", ('extras',), {},
    )
    normcase_mock.return_value = "/some/path/foo"
    assert parse_editable('foo[bar,baz]', 'git') == (
        None, 'file:///some/path/foo', ('bar', 'baz'), {},
    )


def test_exclusive_environment_markers():
    """Make sure RequirementSet accepts several excluding env markers"""
    eq26 = InstallRequirement.from_line(
        "Django>=1.6.10,<1.7 ; python_version == '2.6'")
    ne26 = InstallRequirement.from_line(
        "Django>=1.6.10,<1.8 ; python_version != '2.6'")

    req_set = RequirementSet('', '', '', session=PipSession())
    req_set.add_requirement(eq26)
    req_set.add_requirement(ne26)
    assert req_set.has_requirement('Django')


@pytest.mark.parametrize(('reqs', 'expected_extras'), [
    (['test'], []),
    (['test[e1]'], ['e1']),
    (['test[e2]'], ['e2']),
    (['test[e1]', 'test[e1]'], ['e1']),
    (['test[e1]', 'test[e2]'], ['e1', 'e2']),
    (['test', 'test[e1]'], ['e1']),
    (['test[e1]', 'test'], ['e1']),
    (['test[e1,e2]', 'test[e2,e3]'], ['e1', 'e2', 'e3']),
    (['test[e1,e2]', 'test[e3,e4]'], ['e1', 'e2', 'e3', 'e4']),
    (['test[e1,e2]', 'test[e2,e3]', 'test[e3,e4]'], ['e1', 'e2', 'e3', 'e4']),
])
def test_extra_set_union(reqs, expected_extras):
    """
    RequirementSet will take the set union of all extras specified if the same
    requirement is specified multiple times.
    """
    req_set = RequirementSet('', '', '', session=PipSession())
    req_set.add_requirement(InstallRequirement.from_line('parent'))
    for req in reqs:
        req_set.add_requirement(InstallRequirement.from_line(req), 'parent')
    req = req_set.get_requirement('test')
    assert set(req.extras) == set(expected_extras)
