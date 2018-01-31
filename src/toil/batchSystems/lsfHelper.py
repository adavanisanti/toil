#!/usr/bin/env python
# Adapted from https://github.com/roryk/ipython-cluster-helper
# ipython-cluster-helper is licensed under the MIT license
#
# Copyright 2013-2017 "Rory Kirchne" <rory.kirchner@gmail.com> and contributors
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import print_function
from __future__ import division
from past.utils import old_div
import math
import os
import subprocess
import fnmatch

LSB_PARAMS_FILENAME = "lsb.params"
LSF_CONF_FILENAME = "lsf.conf"
LSF_CONF_ENV = ["LSF_CONFDIR", "LSF_ENVDIR"]
DEFAULT_LSF_UNITS = "KB"
DEFAULT_RESOURCE_UNITS = "MB"


def find(basedir, string):
    """
    walk basedir and return all files matching string
    """
    matches = []
    for root, dirnames, filenames in os.walk(basedir):
        for filename in fnmatch.filter(filenames, string):
            matches.append(os.path.join(root, filename))
    return matches


def find_first_match(basedir, string):
    """
    return the first file that matches string starting from basedir
    """
    matches = find(basedir, string)
    return matches[0] if matches else matches


def get_conf_file(filename, env):
    conf_path = os.environ.get(env)
    if not conf_path:
        return None
    conf_file = find_first_match(conf_path, filename)
    return conf_file


def apply_conf_file(fn, conf_filename):
    for env in LSF_CONF_ENV:
        conf_file = get_conf_file(conf_filename, env)
        if conf_file:
            with open(conf_file) as conf_handle:
                value = fn(conf_handle)
            if value:
                return value
    return None


def per_core_reserve_from_stream(stream):
    for k, v in tokenize_conf_stream(stream):
        if k == "RESOURCE_RESERVE_PER_SLOT":
            return v.upper()
    return None


def get_lsf_units_from_stream(stream):
    for k, v in tokenize_conf_stream(stream):
        if k == "LSF_UNIT_FOR_LIMITS":
            return v
    return None


def parallel_sched_by_slot_from_stream(stream):
    for k, v in tokenize_conf_stream(stream):
        if k == "PARALLEL_SCHED_BY_SLOT":
            return v.upper()
    return None


def tokenize_conf_stream(conf_handle):
    """
    convert the key=val pairs in a LSF config stream to tuples of tokens
    """
    for line in conf_handle:
        if line.startswith("#"):
            continue
        tokens = line.split("=")
        if len(tokens) != 2:
            continue
        yield (tokens[0].strip(), tokens[1].strip())


def apply_bparams(fn):
    """
    apply fn to each line of bparams, returning the result
    """
    cmd = ["bparams", "-a"]
    try:
        output = subprocess.check_output(cmd)
    except:
        return None
    return fn(output.split("\n"))


def apply_lsadmin(fn):
    """
    apply fn to each line of lsadmin, returning the result
    """
    cmd = ["lsadmin", "showconf", "lim"]
    try:
        output = subprocess.check_output(cmd)
    except:
        return None
    return fn(output.split("\n"))


def get_lsf_units(resource=False):
    """
    check if we can find LSF_UNITS_FOR_LIMITS in lsadmin and lsf.conf
    files, preferring the value in bparams, then lsadmin, then the lsf.conf file
    """
    lsf_units = apply_bparams(get_lsf_units_from_stream)
    if lsf_units:
        return lsf_units

    lsf_units = apply_lsadmin(get_lsf_units_from_stream)
    if lsf_units:
        return lsf_units

    lsf_units = apply_conf_file(get_lsf_units_from_stream, LSF_CONF_FILENAME)
    if lsf_units:
        return lsf_units

    # -R usage units are in MB, not KB by default
    if resource:
        return DEFAULT_RESOURCE_UNITS
    else:
        return DEFAULT_LSF_UNITS


def parse_memory_resource(mem):
    """
    Parse memory parameter for -R
    """
    return parse_memory(mem, True)


def parse_memory_limit(mem):
    """
    Parse memory parameter for -M
    """
    return parse_memory(mem, False)


def parse_memory(mem, resource):
    """
    Parse memory parameter
    """
    lsf_unit = get_lsf_units(resource=resource)
    return convert_mb(float(mem) * 1024, lsf_unit)


def per_core_reservation():
    """
    returns True if the cluster is configured for reservations to be per core,
    False if it is per job
    """
    per_core = apply_bparams(per_core_reserve_from_stream)
    if per_core:
        if per_core == "Y":
            return True
        else:
            return False

    per_core = apply_lsadmin(per_core_reserve_from_stream)
    if per_core:
        if per_core == "Y":
            return True
        else:
            return False

    per_core = apply_conf_file(per_core_reserve_from_stream, LSB_PARAMS_FILENAME)
    if per_core and per_core == "Y":
        return True

    return False


def parallel_sched_by_slot():
    """
    returns True if the cluster is configured for span[] to control number of
        job slots
    False if span[] is per processor (the default)
    """
    parallel_sched_by_slot = apply_bparams(parallel_sched_by_slot_from_stream)
    if parallel_sched_by_slot:
        if parallel_sched_by_slot == "Y":
            return True
        else:
            return False

    parallel_sched_by_slot = apply_lsadmin(parallel_sched_by_slot_from_stream)
    if parallel_sched_by_slot:
        if parallel_sched_by_slot == "Y":
            return True
        else:
            return False

    parallel_sched_by_slot = apply_conf_file(
            parallel_sched_by_slot_from_stream, LSB_PARAMS_FILENAME)
    if parallel_sched_by_slot and parallel_sched_by_slot == "Y":
            return True

    return False


def convert_mb(kb, unit):
    UNITS = {"B": -2,
             "KB": -1,
             "MB": 0,
             "GB": 1,
             "TB": 2}
    assert unit in UNITS, ("%s not a valid unit, valid units are %s."
                           % (unit, list(UNITS.keys())))
    return int(old_div(float(kb), float(math.pow(1024, UNITS[unit]))))


if __name__ == "__main__":
    print (get_lsf_units())
    print (per_core_reservation())
