#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Interactive Dependency Resolver

Copyright (C) 2025 Jifeng Wu

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
from __future__ import print_function

import argparse
import datetime
import json
import os.path
import posixpath
import shelve
import sys

# try to import `readline` if it is present
try:
    import readline
except ImportError:
    pass

from packaging.requirements import Requirement, InvalidRequirement
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename

import dateutil.parser

from sortedcontainers import SortedDict
from strcompat import unicode_to_utf_8_string

if sys.version_info < (3,):
    # Python 2
    from urllib2 import urlopen, URLError

    JSONDecodeError = ValueError
else:
    # Python 3
    from urllib.request import urlopen
    from urllib.error import URLError

    JSONDecodeError = json.JSONDecodeError
    raw_input = input
    unicode = str

# Constants

# We don't support changing this.
# Mirrors frequently don't provide PyPI's JSON API.
INDEX_URL = 'https://pypi.org/pypi'

# Auto-detected for the current platform.
# In theory, we could let the user manually specify a different platform,
# but that would involve modifying non-public code in `packaging`.
SYSTEM_TAG_TRIPLES = set(sys_tags())

SCRIPT_PATH = os.path.abspath(os.path.realpath(__file__))
SCRIPT_DIR = os.path.dirname(SCRIPT_PATH)
SHELVE_FILE = os.path.join(SCRIPT_DIR, 'url_json_cache.db')
URL_JSON_CACHE = shelve.open(SHELVE_FILE, flag='n')


def get_json_from_uri(uri):
    """Fetch JSON data from URI with local caching."""
    if uri in URL_JSON_CACHE:
        # returns a copy
        print('Using cached `%s`.' % uri)
        return URL_JSON_CACHE[uri]
    else:
        print('Downloading `%s`...' % uri)
        response = urlopen(uri)
        data = json.load(response)
        URL_JSON_CACHE[uri] = data
        URL_JSON_CACHE.sync()
        print('Finished downloading and caching `%s`.' % uri)
        return data


def get_upload_datetimes_to_compatible_wheel_versions(unicode_package_name, specifier_set, index_url, date):
    """
    Retrieve compatible wheel versions for a package that:
    - Match version constraints
    - Are compatible with current platform
    - Were released before cutoff_date
    """
    url = posixpath.join(
        index_url,
        unicode_to_utf_8_string(unicode_package_name),
        'json'
    )

    package_data = get_json_from_uri(url)
    upload_datetimes_to_compatible_wheel_versions = SortedDict()

    for _, files in package_data.get('releases', {}).items():
        for file in files:
            filename = file['filename']
            upload_time = dateutil.parser.isoparse(file['upload_time'])
            url = file['url']

            if filename.endswith('.whl'):
                (
                    normalized_wheel_name,
                    wheel_version,
                    wheel_build_tag,
                    wheel_tag_triple_frozenset
                ) = parse_wheel_filename(filename)
                
                if specifier_set is None or wheel_version in specifier_set:
                    for tag_triple in wheel_tag_triple_frozenset:
                        if tag_triple in SYSTEM_TAG_TRIPLES and upload_time <= date:
                            upload_datetimes_to_compatible_wheel_versions[upload_time] = wheel_version

    return upload_datetimes_to_compatible_wheel_versions


def get_wheel_requirements(unicode_package_name, wheel_version, index_url):
    """Fetch requirements for a specific wheel version."""
    url = posixpath.join(
        index_url,
        unicode_to_utf_8_string(unicode_package_name),
        str(wheel_version),
        'json'
    )

    wheel_data = get_json_from_uri(url)

    requires_dist = wheel_data.get('info', {}).get('requires_dist', None)

    result = set()
    if requires_dist is not None:
        for wheel_requirement_string in requires_dist:
            while True:
                try:
                    requirement = Requirement(wheel_requirement_string)
                    result.add(requirement)
                    break
                except InvalidRequirement:
                    try:
                        wheel_requirement_string = raw_input('Invalid requirement string `%s`. Fix it: ' % wheel_requirement_string)
                    except EOFError:
                        pass

    return result


def prompt_y_or_n(prompt_message="Please enter Y or N: "):
    """
    Prompts the user to enter Y or N and returns a boolean value.
    - Returns True if user enters 'Y' or 'y'
    - Returns False if user enters 'N' or 'n'
    - Keeps prompting until valid input is received
    """
    while True:
        try:
            user_input = raw_input(prompt_message).strip().upper()
            if user_input == 'Y':
                return True
            elif user_input == 'N':
                return False
        except EOFError:
            pass
        
        print("Invalid input. Please enter Y or N.")


def prompt_version_selection(unicode_package_name, release_dates_to_versions):
    """Ask user to select a version."""
    num_versions = len(release_dates_to_versions)
    release_date_list = list(release_dates_to_versions.keys())
    version_list = list(release_dates_to_versions.values())
    
    if num_versions == 0:
        raise ValueError('No versions to select.')
    elif num_versions == 1:
        version = version_list[0]
        print(u'\nOnly one version %s available for `%s`. Auto-selected.' % (str(version), unicode_package_name))
        return version
    else:
        print(u'\nSelect a version for `%s`:\n' % unicode_package_name)
        for i, (d, v) in enumerate(zip(release_date_list, version_list), start=1):
            print('%d. %s (released on %s)' % (i, v, d.strftime('%Y-%m-%d')))
        
        while True:
            try:
                choice = raw_input('\nEnter a number (1-%d): ' % num_versions).strip()
                idx = int(choice) - 1
                if not (0 <= idx < num_versions):
                    raise IndexError
                return version_list[idx]
            except (EOFError, ValueError, IndexError):
                print('Invalid choice. Try again.')
                continue


class InteractiveDependencyResolver:
    def __init__(self, top_layer_requirements, cutoff_date):
        self.layer = 1
        self.layers_to_requirements = {1: set(top_layer_requirements)}
        self.layers_to_requirements_without_compatible_wheels = {1: set()}
        # { unicode_package_name: (version, layer) }
        self.selected_versions = {}
        
        self.cutoff_date = cutoff_date

    def resolve_layer(self):
        """Resolve requirements for the current layer."""
        print("Resolving layer %d requirements..." % self.layer)
        
        requirements = self.layers_to_requirements[self.layer]
        next_layer_requirements = set()

        for requirement in requirements:
            # e.g., `u'numpy'`
            # `requirement.name` is ALWAYS a `unicode`, even on Python 2!
            unicode_requirement_name = requirement.name
            # e.g., `None`, `<Marker('python_version < "3.7"')>`
            requirement_marker = requirement.marker
            # e.g., `<SpecifierSet('<2')>`, `<SpecifierSet('')>`
            requirement_specifier_set = requirement.specifier
            # e.g., `set([])`, `set(['all'])` in `<Requirement('ipython[all]')>`
            requirement_extras = requirement.extras

            # Do we actually require this requirement?
            try:
                requirement_required = requirement_marker is None or requirement_marker.evaluate()
            # `requirement_marker.evaluate` migh not work,
            # e.g., no definition for `extra` in <Requirement('qtconsole; extra == "all"')>
            # In this case, we ask for manual intervention
            except:
                requirement_required = prompt_y_or_n('\nIs this requirement required: `%s`? [Y/n] ' % str(requirement))

            if not requirement_required:
                continue

            print('\nHandling requirement `%s`' % requirement)

            if unicode_requirement_name in self.selected_versions:
                previously_selected_version, _ = self.selected_versions[unicode_requirement_name]
                
                if previously_selected_version not in requirement_specifier_set:
                    print(u"Conflict: `%s` (previously selected version: `%s`) does not satisfy specifier set `%s`" % (unicode_requirement_name, str(previously_selected_version), str(requirement_specifier_set)))

                    return unicode_requirement_name, False  # Trigger rollback
                else:
                    previously_selected_version, _ = self.selected_versions[unicode_requirement_name]
                    print('Using previously selected version `%s`' % str(previously_selected_version))
            else:
                print('\nGetting compatible wheel versions for `%s`...' % str(requirement))
                try:
                    version_info_dict = get_upload_datetimes_to_compatible_wheel_versions(unicode_requirement_name, requirement_specifier_set, INDEX_URL, self.cutoff_date)
                except URLError as e:
                    print('\nFailed to fetch upload compatible wheel versions for `%s`: `%s` Ignoring `%s`.' % (str(requirement), str(e), str(requirement)))
                    self.layers_to_requirements_without_compatible_wheels[self.layer].add(requirement)
                    continue
                
                if not version_info_dict:
                    print(u"\nNo compatible wheel versions found for `%s`. Ignoring `%s`." % (unicode_requirement_name, str(requirement)))
                    self.layers_to_requirements_without_compatible_wheels[self.layer].add(requirement)
                    continue

                version = prompt_version_selection(unicode_requirement_name, version_info_dict)
                
                print(u'\nGetting next layer requirements from `%s==%s`' % (unicode_requirement_name, str(version)))
                
                try:
                    wheel_requirements = get_wheel_requirements(unicode_requirement_name, version, INDEX_URL)
                except URLError as e:
                    print(u"\nFailed to get next layer requirements from `%s==%s`: `%s` Ignoring this layer's `%s`." % (unicode_requirement_name, str(version), str(e),  str(version)))
                    self.layers_to_requirements_without_compatible_wheels[self.layer].add(requirement)
                    continue
                
                if not wheel_requirements:
                    print('\n`%s==%s` has no next layer requirements. No requirements have been added to layer %d.' % (unicode_requirement_name, str(version), self.layer + 1))
                else:
                    next_layer_requirements.update(wheel_requirements)
                    print(
                        '\nThe following requirements have been added to layer %d: %s' % (
                            self.layer + 1,
                            ', '.join(
                                map(
                                    lambda req: '`%s`' % str(req),
                                    wheel_requirements
                                )
                            )
                        )
                    )

                self.selected_versions[unicode_requirement_name] = (version, self.layer)

        self.layer += 1
        self.layers_to_requirements[self.layer] = next_layer_requirements
        self.layers_to_requirements_without_compatible_wheels[self.layer] = set()
        
        print()
        print("-" * 80)
        print()
        
        return None, not next_layer_requirements

    def rollback(self, conflicting_unicode_package_name):
        """Revert all decisions made after selecting `conflicting_unicode_package_name`."""
        _, target_layer = self.selected_versions[conflicting_unicode_package_name]
        
        self.layer = target_layer
        self.selected_versions = {
            pkg: (v, lyr)
            for pkg, (v, lyr) in self.selected_versions.items()
            if lyr < target_layer
        }
        self.layers_to_requirements = {
            layer: requirements
            for layer, requirements in self.layers_to_requirements.items()
            if layer <= target_layer
        }
        self.layers_to_requirements_without_compatible_wheels = {
            layer: requirements
            for layer, requirements in self.layers_to_requirements_without_compatible_wheels.items()
            if layer <= target_layer
        }


    def run(self):
        while True:
            conflict_pkg_name, is_finished = self.resolve_layer()
            if conflict_pkg_name is not None:
                self.rollback(conflict_pkg_name)

            if is_finished:
                break

        print("Final selected versions:\n")
        for unicode_pkg_name, (ver, _) in self.selected_versions.items():
            print(u"%s==%s" % (unicode_pkg_name, str(ver)))
            
        requirements_without_compatible_wheels = set().union(*(self.layers_to_requirements_without_compatible_wheels.values()))
        if requirements_without_compatible_wheels:
            print("\nRequirements without compatible wheels:\n")
            for req in requirements_without_compatible_wheels:
                print(str(req))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-d',
        '--date',
        required=False,
        default=datetime.datetime.now().strftime('%Y-%m-%d'),
        help='Cutoff date for wheel versions (YYYY-MM-DD)'
    )
    parser.add_argument('requirements', metavar='REQUIREMENT', nargs='+')
    
    args = parser.parse_args()
    
    reqs = set()
    for req_str in args.requirements:
        req = Requirement(req_str)
        reqs.add(req)
    
    date = dateutil.parser.isoparse(args.date)

    return reqs, date


if __name__ == '__main__':
    InteractiveDependencyResolver(*parse_args()).run()