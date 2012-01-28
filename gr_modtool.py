#!/usr/bin/env python
""" A tool for editing GNU Radio modules. """
# Copyright 2010 Communications Engineering Lab, KIT, Germany
#
# This is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with GNU Radio; see the file COPYING.  If not, write to
# the Free Software Foundation, Inc., 51 Franklin Street,
# Boston, MA 02110-1301, USA.
#

import sys
import os
import re
import glob
import base64
import tarfile
from datetime import datetime
from optparse import OptionParser, OptionGroup
from string import Template

### Utility functions ########################################################
def get_command_from_argv(possible_cmds):
    """ Read the requested command from argv. This can't be done with optparse,
    since the option parser isn't defined before the command is known, and
    optparse throws an error."""
    command = None
    for arg in sys.argv:
        if arg[0] == "-":
            continue
        else:
            command = arg
        if command in possible_cmds:
            return arg
    return None

def append_re_line_sequence(filename, linepattern, newline):
    """Detects the re 'linepattern' in the file. After its last occurrence,
    paste 'newline'. If the pattern does not exist, append the new line
    to the file. Then, write. """
    oldfile = open(filename, 'r').read()
    lines = re.findall(linepattern, oldfile, flags=re.MULTILINE)
    if len(lines) == 0:
        open(filename, 'a').write(newline)
        return
    last_line = lines[-1]
    newfile = oldfile.replace(last_line, last_line + newline + '\n')
    open(filename, 'w').write(newfile)

def remove_pattern_from_file(filename, pattern):
    """ Remove all occurrences of a given pattern from a file. """
    oldfile = open(filename, 'r').read()
    open(filename, 'w').write(re.sub(pattern, '', oldfile, flags=re.MULTILINE))

def str_to_fancyc_comment(text):
    """ Return a string as a C formatted comment. """
    l_lines = text.splitlines()
    outstr = "/* " + l_lines[0] + "\n"
    for line in l_lines[1:]:
        outstr += " * " + line + "\n"
    outstr += " */\n"
    return outstr

def str_to_python_comment(text):
    """ Return a string as a Python formatted comment. """
    return re.sub('^', '# ', text, flags=re.MULTILINE)

def get_modname():
    """ Grep the current module's name from gnuradio.project """
    try:
        prfile = open('gnuradio.project', 'r').read()
        regexp = r'projectname\s*=\s*([a-zA-Z0-9-_]+)$'
        return re.search(regexp, prfile, flags=re.MULTILINE).group(1).strip()
    except IOError:
        pass
    # OK, there's no gnuradio.project. So, we need to guess.
    cmfile = open('CMakeLists.txt', 'r').read()
    regexp = r'project\s*\(\s*gr-([a-zA-Z0-9-_]+)\s*CXX'
    return re.search(regexp, cmfile, flags=re.MULTILINE).group(1).strip()

def get_class_dict():
    " Return a dictionary of the available commands in the form command->class "
    classdict = {}
    for g in globals().values():
        try:
            if issubclass(g, ModTool):
                classdict[g.name] = g
                for a in g.aliases:
                    classdict[a] = g
        except (TypeError, AttributeError):
            pass
    return classdict

### Templates ################################################################
Templates = {}
# Default licence
Templates['defaultlicense'] = """
Copyright %d <+YOU OR YOUR COMPANY+>.

This is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3, or (at your option)
any later version.

This software is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this software; see the file COPYING.  If not, write to
the Free Software Foundation, Inc., 51 Franklin Street,
Boston, MA 02110-1301, USA.
""" % datetime.now().year

Templates['work_h'] = """
	int work (int noutput_items,
		gr_vector_const_void_star &input_items,
		gr_vector_void_star &output_items);"""

Templates['generalwork_h'] = """
  int general_work (int noutput_items,
		    gr_vector_int &ninput_items,
		    gr_vector_const_void_star &input_items,
		    gr_vector_void_star &output_items);"""

# Header file of a sync/decimator/interpolator block
Templates['block_h'] = Template("""/* -*- c++ -*- */
$license
#ifndef INCLUDED_${fullblocknameupper}_H
#define INCLUDED_${fullblocknameupper}_H

#include <${modname}_api.h>
#include <$grblocktype.h>

class $fullblockname;
typedef boost::shared_ptr<$fullblockname> ${fullblockname}_sptr;

${modnameupper}_API ${fullblockname}_sptr ${modname}_make_$blockname ($arglist);

/*!
 * \\brief <+description+>
 *
 */
class ${modnameupper}_API $fullblockname : public $grblocktype
{
	friend ${modnameupper}_API ${fullblockname}_sptr ${modname}_make_$blockname ($argliststripped);

	$fullblockname ($argliststripped);

 public:
	~$fullblockname ();

$workfunc
};

#endif /* INCLUDED_${fullblocknameupper}_H */

""")


# Work functions for C++ GR blocks
Templates['work_cpp'] = """work (int noutput_items,
			gr_vector_const_void_star &input_items,
			gr_vector_void_star &output_items)
{
	const float *in = (const float *) input_items[0];
	float *out = (float *) output_items[0];

	// Do <+signal processing+>

	// Tell runtime system how many output items we produced.
	return noutput_items;
}
"""

Templates['generalwork_cpp'] = """general_work (int noutput_items,
			       gr_vector_int &ninput_items,
			       gr_vector_const_void_star &input_items,
			       gr_vector_void_star &output_items)
{
  const float *in = (const float *) input_items[0];
  float *out = (float *) output_items[0];

  // Tell runtime system how many input items we consumed on
  // each input stream.
  consume_each (noutput_items);

  // Tell runtime system how many output items we produced.
  return noutput_items;
}
"""

# C++ file of a GR block
Templates['block_cpp'] = Template("""/* -*- c++ -*- */
$license
#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <gr_io_signature.h>
#include <$fullblockname.h>


${fullblockname}_sptr
${modname}_make_$blockname ($argliststripped)
{
	return $sptr (new $fullblockname ($arglistnotypes));
}


$fullblockname::$fullblockname ($argliststripped)
	: $grblocktype ("$blockname",
		gr_make_io_signature ($inputsig),
		gr_make_io_signature ($outputsig)$decimation)
{
$constructorcontent}


$fullblockname::~$fullblockname ()
{
}
""")

Templates['block_cpp_workcall'] = Template("""

int
$fullblockname::$workfunc
""")

Templates['block_cpp_hierconstructor'] = """
	connect(self(), 0, d_firstblock, 0);
	// connect other blocks
	connect(d_lastblock, 0, self(), 0);
"""

# Header file for QA
Templates['qa_cmakeentry'] = Template("""
add_executable($basename $filename)
target_link_libraries($basename gnuradio-$modname $${Boost_LIBRARIES})
GR_ADD_TEST($basename $basename)
""")

# C++ file for QA
Templates['qa_cpp'] = Template("""/* -*- c++ -*- */
$license

#include <boost/test/unit_test.hpp>

BOOST_AUTO_TEST_CASE(qa_${fullblockname}_t1){
    BOOST_CHECK_EQUAL(2 + 2, 4);
    // BOOST_* test macros <+here+>
}

BOOST_AUTO_TEST_CASE(qa_${fullblockname}_t2){
    BOOST_CHECK_EQUAL(2 + 2, 4);
    // BOOST_* test macros <+here+>
}

""")

# Python QA code
Templates['qa_python'] = Template("""#!/usr/bin/env python
$license
#

from gnuradio import gr, gr_unittest
import ${modname}$swig

class qa_$blockname (gr_unittest.TestCase):

    def setUp (self):
        self.tb = gr.top_block ()

    def tearDown (self):
        self.tb = None

    def test_001_t (self):
        # set up fg
        self.tb.run ()
        # check data


if __name__ == '__main__':
    gr_unittest.main ()
""")


Templates['hier_python'] = Template('''$license

from gnuradio import gr

class $blockname(gr.hier_block2):
    def __init__(self, $arglist):
    """
    docstring
	"""
        gr.hier_block2.__init__(self, "$blockname",
				gr.io_signature($inputsig),  # Input signature
				gr.io_signature($outputsig)) # Output signature

        # Define blocks
        self.connect()

''')

# Implementation file, C++ header
Templates['impl_h'] = Template('''/* -*- c++ -*- */
$license
#ifndef INCLUDED_QA_${fullblocknameupper}_H
#define INCLUDED_QA_${fullblocknameupper}_H

class $fullblockname
{
 public:
	$fullblockname($arglist);
	~$fullblockname();


 private:

};

#endif /* INCLUDED_${fullblocknameupper}_H */

''')

# Implementation file, C++ source
Templates['impl_cpp'] = Template('''/* -*- c++ -*- */
$license

#include <$fullblockname.h>


$fullblockname::$fullblockname($argliststripped)
{
}


$fullblockname::~$fullblockname()
{
}
''')


Templates['grc_xml'] = Template('''<?xml version="1.0"?>
<block>
  <name>$blockname</name>
  <key>$fullblockname</key>
  <category>$modname</category>
  <import>import $modname</import>
  <make>$modname.$blockname($arglistnotypes)</make>
  <!-- Make one 'param' node for every Parameter you want settable from the GUI.
       Sub-nodes:
       * name
       * key (makes the value accessible as $$keyname, e.g. in the make node)
       * type -->
  <param>
    <name>...</name>
    <key>...</key>
    <type>...</type>
  </param>

  <!-- Make one 'sink' node per input. Sub-nodes:
       * name (an identifier for the GUI)
       * type
       * vlen
       * optional (set to 1 for optional inputs) -->
  <sink>
    <name>in</name>
    <type><!-- e.g. int, real, complex, byte, short, xxx_vector, ...--></type>
  </sink>

  <!-- Make one 'source' node per output. Sub-nodes:
       * name (an identifier for the GUI)
       * type
       * vlen
       * optional (set to 1 for optional inputs) -->
  <source>
    <name>out</name>
    <type><!-- e.g. int, real, complex, byte, short, xxx_vector, ...--></type>
  </source>
</block>
''')

# Usage
Templates['usage'] = """
gr_modtool.py <command> [options] -- Run <command> with the given options.
gr_modtool.py help -- Show a list of commands.
gr_modtool.py help <command> -- Shows the help for a given command. """

### Code generator class #####################################################
class CodeGenerator(object):
    """ Creates the skeleton files. """
    def __init__(self):
        self.defvalpatt = re.compile(" *=[^,)]*")
        self.grtypelist = {
                'sync': 'gr_sync_block',
                'decimator': 'gr_sync_decimator',
                'interpolator': 'gr_sync_interpolator',
                'general': 'gr_block',
                'hiercpp': 'gr_hier_block2',
                'impl': ''}

    def strip_default_values(self, string):
        """ Strip default values from a C++ argument list. """
        return self.defvalpatt.sub("", string)

    def strip_arg_types(self, string):
        """" Strip the argument types from a list of arguments
        Example: "int arg1, double arg2" -> "arg1, arg2" """
        string = self.strip_default_values(string)
        return ", ".join([part.strip().split(' ')[-1] for part in string.split(',')])

    def get_template(self, tpl_id, **kwargs):
        ''' Request a skeleton file from a template.
        First, it prepares a dictionary which the template generator
        can use to fill in the blanks, then it uses Python's
        Template() function to create the file contents. '''
        # Licence
        if tpl_id in ('block_h', 'block_cpp', 'qa_h', 'qa_cpp', 'impl_h', 'impl_cpp'):
            kwargs['license'] = str_to_fancyc_comment(kwargs['license'])
        elif tpl_id in ('qa_python', 'hier_python'):
            kwargs['license'] = str_to_python_comment(kwargs['license'])
        # Standard values for templates
        kwargs['argliststripped'] = self.strip_default_values(kwargs['arglist'])
        kwargs['arglistnotypes'] = self.strip_arg_types(kwargs['arglist'])
        kwargs['fullblocknameupper'] = kwargs['fullblockname'].upper()
        kwargs['modnameupper'] = kwargs['modname'].upper()
        kwargs['grblocktype'] = self.grtypelist[kwargs['blocktype']]
        # Specials for qa_python
        kwargs['swig'] = ''
        if kwargs['blocktype'] != 'hierpython':
            kwargs['swig'] = '_swig'
        # Specials for block_h
        if tpl_id == 'block_h':
            if kwargs['blocktype'] == 'general':
                kwargs['workfunc'] = Templates['generalwork_h']
            elif kwargs['blocktype'] == 'hiercpp':
                kwargs['workfunc'] = ''
            else:
                kwargs['workfunc'] = Templates['work_h']
        # Specials for block_cpp
        if tpl_id == 'block_cpp':
            return self._get_block_cpp(kwargs)
        # All other ones
        return Templates[tpl_id].substitute(kwargs)

    def _get_block_cpp(self, kwargs):
        '''This template is a bit fussy, so it needs some extra attention.'''
        kwargs['decimation'] = ''
        kwargs['constructorcontent'] = ''
        kwargs['sptr'] = kwargs['fullblockname'] + '_sptr'
        if kwargs['blocktype'] == 'decimator':
            kwargs['decimation'] = ", <+decimation+>"
        elif kwargs['blocktype'] == 'interpolator':
            kwargs['decimation'] = ", <+interpolation+>"
        if kwargs['blocktype'] == 'general':
            kwargs['workfunc'] = Templates['generalwork_cpp']
        elif kwargs['blocktype'] == 'hiercpp':
            kwargs['workfunc'] = ''
            kwargs['constructorcontent'] = Templates['block_cpp_hierconstructor']
            kwargs['sptr'] = 'gnuradio::get_initial_sptr'
            return Templates['block_cpp'].substitute(kwargs)
        else:
            kwargs['workfunc'] = Templates['work_cpp']
        return Templates['block_cpp'].substitute(kwargs) + \
               Templates['block_cpp_workcall'].substitute(kwargs)

### CMakeFile.txt editor class ###############################################
class CMakeFileEditor(object):
    """A tool for editing CMakeLists.txt files. """
    def __init__(self, filename, separator=' '):
        self.filename = filename
        fid = open(filename, 'r')
        self.cfile = fid.read()
        self.separator = separator

    def get_entry_value(self, entry, to_ignore=''):
        """ Get the value of an entry.
        to_ignore is the part of the entry you don't care about. """
        regexp = '%s\(%s([^()]+)\)' % (entry, to_ignore)
        mobj = re.search(regexp, self.cfile, flags=re.MULTILINE)
        if mobj is None:
            return None
        value = mobj.groups()[0].strip()
        return value

    def append_value(self, entry, value, to_ignore=''):
        """ Add a value to an entry. """
        regexp = '(%s\([^()]*?)\s*?(\s?%s)\)' % (entry, to_ignore)
        substi = r'\1' + self.separator + value + r'\2)'
        self.cfile = re.sub(regexp, substi, self.cfile,
                            count=1, flags=re.MULTILINE)

    def remove_value(self, entry, value, to_ignore=''):
        """Remove a value from an entry."""
        regexp = '^\s*(%s\(\s*%s[^()]*?\s*)%s\s*([^()]*\))' % (entry, to_ignore, value)
        self.cfile = re.sub(regexp, r'\1\2', self.cfile, count=1, flags=re.MULTILINE)

    def delete_entry(self, entry, value_pattern=''):
        """Remove an entry from the current buffer."""
        regexp = '%s\s*\([^()]*%s[^()]*\)[^\n]*\n' % (entry, value_pattern)
        self.cfile = re.sub(regexp, '', self.cfile, count=1, flags=re.MULTILINE)

    def write(self):
        """ Write the changes back to the file. """
        open(self.filename, 'w').write(self.cfile)

    def remove_double_newlines(self):
        """Simply clear double newlines from the file buffer."""
        self.cfile = re.sub('\n\n\n+', '\n\n', self.cfile, flags=re.MULTILINE)

### ModTool base class #######################################################
class ModTool(object):
    """ Base class for all modtool command classes. """
    def __init__(self):
        self._subdirs = ['lib', 'include', 'python', 'swig', 'grc'] # List subdirs where stuff happens
        self._has_subdirs = {}
        self._skip_subdirs = {}
        self._info = {}
        for subdir in self._subdirs:
            self._has_subdirs[subdir] = False
            self._skip_subdirs[subdir] = False
        self.parser = self.setup_parser()
        self.tpl = CodeGenerator()
        self.args = None
        self.options = None
        self._dir = None

    def setup_parser(self):
        """ Init the option parser. If derived classes need to add options,
        override this and call the parent function. """
        parser = OptionParser(usage=Templates['usage'], add_help_option=False)
        ogroup = OptionGroup(parser, "General options")
        ogroup.add_option("-h", "--help", action="help", help="Displays this help message.")
        ogroup.add_option("-d", "--directory", type="string", default=".",
                help="Base directory of the module.")
        ogroup.add_option("-n", "--module-name", type="string", default=None,
                help="Name of the GNU Radio module. If possible, this gets detected from CMakeLists.txt.")
        ogroup.add_option("-N", "--block-name", type="string", default=None,
                help="Name of the block, minus the module name prefix.")
        ogroup.add_option("--skip-lib", action="store_true", default=False,
                help="Don't do anything in the lib/ subdirectory.")
        ogroup.add_option("--skip-swig", action="store_true", default=False,
                help="Don't do anything in the swig/ subdirectory.")
        ogroup.add_option("--skip-python", action="store_true", default=False,
                help="Don't do anything in the python/ subdirectory.")
        ogroup.add_option("--skip-grc", action="store_true", default=True,
                help="Don't do anything in the grc/ subdirectory.")
        parser.add_option_group(ogroup)
        return parser


    def setup(self):
        """ Initialise all internal variables, such as the module name etc. """
        (options, self.args) = self.parser.parse_args()
        self._dir = options.directory
        if not self._check_directory(self._dir):
            print "No GNU Radio module found in the given directory. Quitting."
            sys.exit(1)
        print "Operating in directory " + self._dir

        if options.skip_lib:
            print "Force-skipping 'lib'."
            self._skip_subdirs['lib'] = True
        if options.skip_python:
            print "Force-skipping 'python'."
            self._skip_subdirs['python'] = True
        if options.skip_swig:
            print "Force-skipping 'swig'."
            self._skip_subdirs['swig'] = True

        if options.module_name is not None:
            self._info['modname'] = options.module_name
        else:
            self._info['modname'] = get_modname()
        print "GNU Radio module name identified: " + self._info['modname']
        self._info['blockname'] = options.block_name
        self.options = options


    def run(self):
        """ Override this. """
        pass


    def _check_directory(self, directory):
        """ Guesses if dir is a valid GNU Radio module directory by looking for
        gnuradio.project and at least one of the subdirs lib/, python/ and swig/.
        Changes the directory, if valid. """
        has_makefile = False
        try:
            files = os.listdir(directory)
            os.chdir(directory)
        except OSError:
            print "Can't read or chdir to directory %s." % directory
            return False
        for f in files:
            if (os.path.isfile(f) and
                    f == 'CMakeLists.txt' and
                    re.search('find_package\(GnuradioCore\)', open(f).read()) is not None):
                has_makefile = True
            elif os.path.isdir(f):
                if (f in self._has_subdirs.keys()):
                    self._has_subdirs[f] = True
                else:
                    self._skip_subdirs[f] = True
        return bool(has_makefile and (self._has_subdirs.values()))


    def _get_mainswigfile(self):
        """ Find out which name the main SWIG file has. In particular, is it
            a MODNAME.i or a MODNAME_swig.i? Returns None if none is found. """
        modname = self._info['modname']
        swig_files = (modname + '.i',
                      modname + '_swig.i')
        for fname in swig_files:
            if os.path.isfile(os.path.join(self._dir, 'swig', fname)):
                return fname
        return None


### Add new block module #####################################################
class ModToolAdd(ModTool):
    """ Add block to the out-of-tree module. """
    name = 'add'
    aliases = ('insert',)
    _block_types = ('sink', 'source', 'sync', 'decimator', 'interpolator',
                    'general', 'hiercpp', 'hierpython', 'impl')
    def __init__(self):
        ModTool.__init__(self)
        self._info['inputsig'] = "<+MIN_IN+>, <+MAX_IN+>, sizeof (<+float+>)"
        self._info['outputsig'] = "<+MIN_IN+>, <+MAX_IN+>, sizeof (<+float+>)"
        self._add_cc_qa = False
        self._add_py_qa = False


    def setup_parser(self):
        parser = ModTool.setup_parser(self)
        parser.usage = '%prog add [options]. \n Call %prog without any options to run it interactively.'
        ogroup = OptionGroup(parser, "Add module options")
        ogroup.add_option("-t", "--block-type", type="choice",
                choices=self._block_types, default=None, help="One of %s." % ', '.join(self._block_types))
        ogroup.add_option("--license-file", type="string", default=None,
                help="File containing the license header for every source code file.")
        ogroup.add_option("--argument-list", type="string", default=None,
                help="The argument list for the constructor and make functions.")
        ogroup.add_option("--add-python-qa", action="store_true", default=None,
                help="If given, Python QA code is automatically added if possible.")
        ogroup.add_option("--add-cpp-qa", action="store_true", default=None,
                help="If given, C++ QA code is automatically added if possible.")
        ogroup.add_option("--skip-cmakefiles", action="store_true", default=False,
                help="If given, only source files are written, but CMakeLists.txt files are left unchanged.")
        parser.add_option_group(ogroup)
        return parser


    def setup(self):
        ModTool.setup(self)
        options = self.options
        self._info['blocktype'] = options.block_type
        if self._info['blocktype'] is None:
            while self._info['blocktype'] not in self._block_types:
                self._info['blocktype'] = raw_input("Enter code type: ")
                if self._info['blocktype'] not in self._block_types:
                    print 'Must be one of ' + str(self._block_types)
        print "Code is of type: " + self._info['blocktype']

        if (not self._has_subdirs['lib'] and self._info['blocktype'] != 'hierpython') or \
           (not self._has_subdirs['python'] and self._info['blocktype'] == 'hierpython'):
            print "Can't do anything if the relevant subdir is missing. See ya."
            sys.exit(1)

        if self._info['blockname'] is None:
            if len(self.args) >= 2:
                self._info['blockname'] = self.args[1]
            else:
                self._info['blockname'] = raw_input("Enter name of block/code (without module name prefix): ")
        if not re.match('[a-zA-Z0-9_]+', self._info['blockname']):
            print 'Invalid block name.'
            sys.exit(2)
        print "Block/code identifier: " + self._info['blockname']

        self._info['prefix'] = self._info['modname']
        if self._info['blocktype'] == 'impl':
            self._info['prefix'] += 'i'
        self._info['fullblockname'] = self._info['prefix'] + '_' + self._info['blockname']
        print "Full block/code identifier is: " + self._info['fullblockname']

        self._info['license'] = self.setup_choose_license()

        if options.argument_list is not None:
            self._info['arglist'] = options.argument_list
        else:
            self._info['arglist'] = raw_input('Enter valid argument list, including default arguments: ')

        if not (self._info['blocktype'] in ('impl') or self._skip_subdirs['python']):
            self._add_py_qa = options.add_python_qa
            if self._add_py_qa is None:
                self._add_py_qa = (raw_input('Add Python QA code? [Y/n] ').lower() != 'n')
        if not (self._info['blocktype'] in ('hierpython') or self._skip_subdirs['lib']):
            self._add_cc_qa = options.add_cpp_qa
            if self._add_cc_qa is None:
                self._add_cc_qa = (raw_input('Add C++ QA code? [Y/n] ').lower() != 'n')

        if self._info['blocktype'] == 'source':
            self._info['inputsig'] = "0, 0, 0"
            self._info['blocktype'] = "sync"
        if self._info['blocktype'] == 'sink':
            self._info['outputsig'] = "0, 0, 0"
            self._info['blocktype'] = "sync"


    def setup_choose_license(self):
        """ Select a license by the following rules, in this order:
        1) The contents of the file given by --license-file
        2) The contents of the file LICENSE or LICENCE in the modules
           top directory
        3) The default license. """
        if self.options.license_file is not None \
            and os.path.isfile(self.options.license_file):
            return open(self.options.license_file).read()
        elif os.path.isfile('LICENSE'):
            return open('LICENSE').read()
        elif os.path.isfile('LICENCE'):
            return open('LICENCE').read()
        else:
            return Templates['defaultlicense']

    def _write_tpl(self, tpl, path, fname):
        """ Shorthand for writing a substituted template to a file"""
        print "Adding file '%s'..." % fname
        open(os.path.join(path, fname), 'w').write(self.tpl.get_template(tpl, **self._info))

    def run(self):
        """ Go, go, go. """
        if self._info['blocktype'] != 'hierpython' and not self._skip_subdirs['lib']:
            self._run_lib()
        has_swig = self._info['blocktype'] in (
                'sink',
                'source',
                'sync',
                'decimator',
                'interpolator',
                'general',
                'hiercpp') and self._has_subdirs['swig'] and not self._skip_subdirs['swig']
        if has_swig:
            self._run_swig()
        if self._add_py_qa:
            self._run_python_qa()
        if self._info['blocktype'] == 'hierpython':
            self._run_python_hierblock()
        if (not self._skip_subdirs['grc'] and self._has_subdirs['grc'] and
            (self._info['blocktype'] == 'hierpython' or has_swig)):
            self._run_grc()


    def _run_lib(self):
        """ Do everything that needs doing in the subdir 'lib' and 'include'.
        - add .cc and .h files
        - include them into CMakeLists.txt
        - check if C++ QA code is req'd
        - if yes, create qa_*.{cc,h} and add them to CMakeLists.txt
        """
        print "Traversing lib..."
        fname_h = self._info['fullblockname'] + '.h'
        fname_cc = self._info['fullblockname'] + '.cc'
        if self._info['blocktype'] in ('source', 'sink', 'sync', 'decimator',
                                       'interpolator', 'general', 'hiercpp'):
            self._write_tpl('block_h', 'include', fname_h)
            self._write_tpl('block_cpp', 'lib', fname_cc)
        elif self._info['blocktype'] == 'impl':
            self._write_tpl('impl_h', 'include', fname_h)
            self._write_tpl('impl_cpp', 'lib', fname_cc)
        if not self.options.skip_cmakefiles:
            ed = CMakeFileEditor('lib/CMakeLists.txt')
            ed.append_value('add_library', fname_cc)
            ed.write()
            ed = CMakeFileEditor('include/CMakeLists.txt', '\n    ')
            ed.append_value('install', fname_h, 'DESTINATION[^()]+')
            ed.write()

        if not self._add_cc_qa:
            return
        fname_qa_cc = 'qa_%s' % fname_cc
        self._write_tpl('qa_cpp', 'lib', fname_qa_cc)
        if not self.options.skip_cmakefiles:
            open('lib/CMakeLists.txt', 'a').write(Template.substitute(Templates['qa_cmakeentry'],
                                          {'basename': os.path.splitext(fname_qa_cc)[0],
                                           'filename': fname_qa_cc,
                                           'modname': self._info['modname']}))
            ed = CMakeFileEditor('lib/CMakeLists.txt')
            ed.remove_double_newlines()
            ed.write()

    def _run_swig(self):
        """ Do everything that needs doing in the subdir 'swig'.
        - Edit main *.i file
        """
        print "Traversing swig..."
        fname_mainswig = self._get_mainswigfile()
        if fname_mainswig is None:
            print 'Warning: No main swig file found.'
            return
        fname_mainswig = os.path.join('swig', fname_mainswig)
        print "Editing %s..." % fname_mainswig
        swig_block_magic_str = 'GR_SWIG_BLOCK_MAGIC(%s,%s);\n%%include "%s"\n' % (
                                   self._info['modname'],
                                   self._info['blockname'],
                                   self._info['fullblockname'] + '.h')
        if re.search('#include', open(fname_mainswig, 'r').read()):
            append_re_line_sequence(fname_mainswig, '^#include.*\n',
                    '#include "%s.h"' % self._info['fullblockname'])
            append_re_line_sequence(fname_mainswig,
                                    '^GR_SWIG_BLOCK_MAGIC\(.*?\);\s*?\%include.*\s*',
                                    swig_block_magic_str)
        else: # I.e., if the swig file is empty
            oldfile = open(fname_mainswig, 'r').read()
            oldfile = re.sub('^%\{\n', '%%{\n#include "%s.h"\n' % self._info['fullblockname'],
                           oldfile, count=1, flags=re.MULTILINE)
            oldfile = re.sub('^%\}\n', '%}\n\n' + swig_block_magic_str,
                           oldfile, count=1, flags=re.MULTILINE)
            open(fname_mainswig, 'w').write(oldfile)


    def _run_python_qa(self):
        """ Do everything that needs doing in the subdir 'python' to add
        QA code.
        - add .py files
        - include in CMakeLists.txt
        """
        print "Traversing python..."
        fname_py_qa = 'qa_' + self._info['fullblockname'] + '.py'
        self._write_tpl('qa_python', 'python', fname_py_qa)
        os.chmod(os.path.join('python', fname_py_qa), 0755)
        print "Editing python/CMakeLists.txt..."
        open('python/CMakeLists.txt', 'a').write(
                'GR_ADD_TEST(qa_%s ${PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/%s)\n' % \
                  (self._info['blockname'], fname_py_qa))

    def _run_python_hierblock(self):
        """ Do everything that needs doing in the subdir 'python' to add
        a Python hier_block.
        - add .py file
        - include in CMakeLists.txt
        """
        print "Traversing python..."
        fname_py = self._info['blockname'] + '.py'
        self._write_tpl('hier_python', 'python', fname_py)
        ed = CMakeFileEditor('python/CMakeLists.txt')
        ed.append_value('GR_PYTHON_INSTALL', fname_py, 'DESTINATION[^()]+')
        ed.write()

    def _run_grc(self):
        """ Do everything that needs doing in the subdir 'grc' to add
        a GRC bindings XML file.
        - add .xml file
        - include in CMakeLists.txt
        """
        print "Traversing grc..."
        fname_grc = self._info['fullblockname'] + '.xml'
        self._write_tpl('grc_xml', 'grc', fname_grc)
        print "Editing grc/CMakeLists.txt..."
        ed = CMakeFileEditor('grc/CMakeLists.txt', '\n    ')
        ed.append_value('install', fname_grc, 'DESTINATION[^()]+')
        ed.write()

### Remove module ###########################################################
class ModToolRemove(ModTool):
    """ Remove block (delete files and remove Makefile entries) """
    name = 'remove'
    aliases = ('rm', 'del')
    def __init__(self):
        ModTool.__init__(self)

    def setup_parser(self):
        " Initialise the option parser for 'gr_modtool.py rm' "
        parser = ModTool.setup_parser(self)
        parser.usage = '%prog rm [options]. \n Call %prog without any options to run it interactively.'
        ogroup = OptionGroup(parser, "Remove module options")
        ogroup.add_option("-p", "--pattern", type="string", default=None,
                help="Filter possible choices for blocks to be deleted.")
        ogroup.add_option("-y", "--yes", action="store_true", default=False,
                help="Answer all questions with 'yes'.")
        parser.add_option_group(ogroup)
        return parser

    def setup(self):
        ModTool.setup(self)
        options = self.options
        if options.pattern is not None:
            self._info['pattern'] = options.pattern
        elif options.block_name is not None:
            self._info['pattern'] = options.block_name
        elif len(self.args) >= 2:
            self._info['pattern'] = self.args[1]
        else:
            self._info['pattern'] = raw_input('Which blocks do you want to delete? (Regex): ')
        if len(self._info['pattern']) == 0:
            self._info['pattern'] = '.'
        self._info['yes'] = options.yes

    def run(self):
        """ Go, go, go! """
        def _remove_cc_test_case(filename=None, ed=None):
            """ Special function that removes the occurrences of a qa*.cc file
            from the CMakeLists.txt. """
            if filename[:2] != 'qa':
                return
            filebase = os.path.splitext(filename)[0]
            ed.delete_entry('add_executable', filebase)
            ed.delete_entry('target_link_libraries', filebase)
            ed.delete_entry('GR_ADD_TEST', filebase)
            ed.remove_double_newlines()

        def _make_swig_regex(filename):
            filebase = os.path.splitext(filename)[0]
            pyblockname = filebase.replace(self._info['modname'] + '_', '')
            regexp = r'^\s*GR_SWIG_BLOCK_MAGIC\(%s,\s*%s\);\s*%%include\s*"%s"\s*' % \
                    (self._info['modname'], pyblockname, filename)
            return regexp

        if not self._skip_subdirs['lib']:
            self._run_subdir('lib', ('*.cc', '*.h'), ('add_library',),
                             cmakeedit_func=_remove_cc_test_case)
        if not self._skip_subdirs['include']:
            incl_files_deleted = self._run_subdir('include', ('*.cc', '*.h'), ('install',),
                             cmakeedit_func=_remove_cc_test_case)
        if not self._skip_subdirs['swig']:
            for f in incl_files_deleted:
                remove_pattern_from_file('swig/'+self._get_mainswigfile(), _make_swig_regex(f))
                remove_pattern_from_file('swig/'+self._get_mainswigfile(), '#include "%s"' % f)
        if not self._skip_subdirs['python']:
            py_files_deleted = self._run_subdir('python', ('*.py',), ('GR_PYTHON_INSTALL',))
            for f in py_files_deleted:
                remove_pattern_from_file('python/__init__.py', '.*import.*%s.*' % f[:-3])
        if not self._skip_subdirs['grc']:
            self._run_subdir('grc', ('*.xml',), ('install',))


    def _run_subdir(self, path, globs, makefile_vars, cmakeedit_func=None):
        """ Delete all files that match a certain pattern in path.
        path - The directory in which this will take place
        globs - A tuple of standard UNIX globs of files to delete (e.g. *.xml)
        makefile_vars - A tuple with a list of CMakeLists.txt-variables which
                        may contain references to the globbed files
        cmakeedit_func - If the CMakeLists.txt needs special editing, use this
        """
        # 1. Create a filtered list
        files = []
        for g in globs:
            files = files + glob.glob("%s/%s"% (path, g))
        files_filt = []
        print "Searching for matching files in %s/:" % path
        for f in files:
            if re.search(self._info['pattern'], os.path.basename(f)) is not None:
                files_filt.append(f)
            if path is "swig":
                files_filt.append(f)
        if len(files_filt) == 0:
            print "None found."
            return []
        # 2. Delete files, Makefile entries and other occurences
        files_deleted = []
        ed = CMakeFileEditor('%s/CMakeLists.txt' % path)
        yes = self._info['yes']
        for f in files_filt:
            b = os.path.basename(f)
            if not yes:
                ans = raw_input("Really delete %s? [Y/n/a/q]: " % f).lower().strip()
                if ans == 'a':
                    yes = True
                if ans == 'q':
                    sys.exit(0)
                if ans == 'n':
                    continue
            files_deleted.append(b)
            print "Deleting %s." % f
            os.unlink(f)
            print "Deleting occurrences of %s from %s/CMakeLists.txt..." % (b, path)
            for var in makefile_vars:
                ed.remove_value(var, b)
            if cmakeedit_func is not None:
                cmakeedit_func(b, ed)
        ed.write()
        return files_deleted


### The entire new module zipfile as base64 encoded tar.bz2  ###
NEWMOD_TARFILE = """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
R10/Z9dcP5Xc2fwjkfdi7+UHfxju+EBN1BKFOUBMiIsBBEAMuQPPHlXI8wQG1+f7fYdj4je/AEPD
RuxBTMH4azZGFMMthSRCD5fwaEt8j2eRxTFPhgtuWo8LLpj0CD7efGDs/ufzDh4N+z07Dpy2ltMe
zTw7uXlpcOZFcyR/PGMSM3I7VdvGziuurhJfmTgvxTEWQRcnfruGuHlXI82uy7Jiw4DuLIQ9rOV+
0p/fMI07Mk6D1RFiuSilsugphAixJO6Cou58TgyO9g8THzvU0Ob5WOlDcFm42DBispKVJKJumVVR
3ToJLoafni5yMFtM5dCQxbNoVcjyjAmOVkjZYNP4s4Dnnsv8Nh7PpKG2MB1usVaUhRQBlFSVwVFm
nWZke5LRyqkbHcok4ens26Y2hTTbXyc9BwGzjfgLcMeHKEG354dgA8ABhBSiB4PbA/HIve24uidX
TJlPJFk82wnZVSRzX1VkpLbBap17ow5CdT4ZWKAptnFSTAuFgZEC2nIbUHCLw48h6cv2a0ZrYraj
H4z+PbuvKdMoYA/oYIWx8OKcsARofl3f3mXw6TBIx3cNenvHOZFbqdE6crPUiobQK9VwrKsSjzHo
5FMGEaNNdkYLFLHDbMgM0VZosZkE6oRXYpL6FmV00B+n0/F2e+5u2RfLzw3yR9nrLY2xDAHt6TZS
sSOSbW4vz7UPYdNqtHKtQ4RpI+gaNrbBHBk9euzl7q+bv0/1cDCbhxu0x4ae/1cuG30uhpmgiGxj
kbe6GxvhveJsSQuUQ57Vacp4XWYKLExNTaCwVpqefiEG94KlAtMdEs0eem7dKYEXTHsxB3q5Dm4p
6XCup0g5T2ArXOHHvWK1nj2r4sDNt+yoyOqkptcnL1ycvXJy9T13cnL1ycvXJy9cnL1yc13cnNd3
JzXdyc13cnMXdycvXJzXdycvXJy9T22u7k5ru5OXrk5runru5FObXdyc13cnNru5OYu7k5i7uTmL
u5OXrk5euTmAu6eu7k5euTl65I3KjI3KpuqjkODr8Z9x9ZVVa/p77i97r3decKuFFprfY7DBsVVQ
dDHweNpDW0Pg8N3kY4YP6CMeGh2Y5ctPhpptj+Qy4d/NyPuwfEGhg05aaYns20hGNtDhtp3MEnk0
PZ3cOhpwPZ2H5Mcjl9n4OxJgOnxs6Y4GMDyctPDB9/vp8m2nyY2wdP2cNg8jHcfOOJsWfiOBLu7T
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"""
### New out-of-tree-mod module ###############################################
class ModToolNewModule(ModTool):
    """ Create a new out-of-tree module """
    name = 'newmod'
    aliases = ('nm', 'create')
    def __init__(self):
        ModTool.__init__(self)

    def setup_parser(self):
        " Initialise the option parser for 'gr_modtool.py newmod' "
        parser = ModTool.setup_parser(self)
        #parser.usage = '%prog rm [options]. \n Call %prog without any options to run it interactively.'
        #ogroup = OptionGroup(parser, "New out-of-tree module options")
        #parser.add_option_group(ogroup)
        return parser

    def setup(self):
        (options, self.args) = self.parser.parse_args()
        self._info['modname'] = options.module_name
        if self._info['modname'] is None:
            if len(self.args) >= 2:
                self._info['modname'] = self.args[1]
            else:
                self._info['modname'] = raw_input('Name of the new module: ')
        if not re.match('[a-zA-Z0-9_]+', self._info['modname']):
            print 'Invalid module name.'
            sys.exit(2)
        self._dir = options.directory
        if self._dir == '.':
            self._dir = './gr-%s' % self._info['modname']
        print 'Module directory is "%s".' % self._dir
        try:
            os.stat(self._dir)
        except OSError:
            pass # This is what should happen
        else:
            print 'The given directory exists.'
            sys.exit(2)

    def run(self):
        """ Go, go, go! """
        print "Creating directory..."
        try:
            os.mkdir(self._dir)
            os.chdir(self._dir)
        except OSError:
            print 'Could not create directory %s. Quitting.' % self._dir
            sys.exit(2)
        print "Copying howto example..."
        open('tmp.tar.bz2', 'wb').write(base64.b64decode(NEWMOD_TARFILE))
        print "Unpacking..."
        tar = tarfile.open('tmp.tar.bz2', mode='r:bz2')
        tar.extractall()
        tar.close()
        os.unlink('tmp.tar.bz2')
        print "Replacing occurences of 'howto' to '%s'..." % self._info['modname']
        skip_dir_re = re.compile('^..cmake|^..apps|^..grc|doxyxml')
        for root, dirs, files in os.walk('.'):
            if skip_dir_re.search(root):
                continue
            for filename in files:
                f = os.path.join(root, filename)
                s = open(f, 'r').read()
                s = s.replace('howto', self._info['modname'])
                s = s.replace('HOWTO', self._info['modname'].upper())
                open(f, 'w').write(s)
                if filename[0:5] == 'howto':
                    newfilename = filename.replace('howto', self._info['modname'])
                    os.rename(f, os.path.join(root, newfilename))
        print "Done."
        print "Use 'gr_modtool add' to add a new block to this currently empty module."


### Help module ##############################################################
def print_class_descriptions():
    ''' Go through all ModTool* classes and print their name,
        alias and description. '''
    desclist = []
    for gvar in globals().values():
        try:
            if issubclass(gvar, ModTool) and not issubclass(gvar, ModToolHelp):
                desclist.append((gvar.name, ','.join(gvar.aliases), gvar.__doc__))
        except (TypeError, AttributeError):
            pass
    print 'Name      Aliases          Description'
    print '====================================================================='
    for description in desclist:
        print '%-8s  %-12s    %s' % description

class ModToolHelp(ModTool):
    ''' Show some help. '''
    name = 'help'
    aliases = ('h', '?')
    def __init__(self):
        ModTool.__init__(self)

    def setup(self):
        pass

    def run(self):
        cmd_dict = get_class_dict()
        cmds = cmd_dict.keys()
        cmds.remove(self.name)
        for a in self.aliases:
            cmds.remove(a)
        help_requested_for = get_command_from_argv(cmds)
        if help_requested_for is None:
            print 'Usage:' + Templates['usage']
            print '\nList of possible commands:\n'
            print_class_descriptions()
            return
        cmd_dict[help_requested_for]().setup_parser().print_help()

### Main code ################################################################
def main():
    """ Here we go. Parse command, choose class and run. """
    cmd_dict = get_class_dict()
    command = get_command_from_argv(cmd_dict.keys())
    if command is None:
        print 'Usage:' + Templates['usage']
        sys.exit(2)
    modtool = cmd_dict[command]()
    modtool.setup()
    modtool.run()

if __name__ == '__main__':
    main()

