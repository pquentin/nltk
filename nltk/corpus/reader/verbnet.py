# Natural Language Toolkit: VerbNet Corpus Reader
#
# Copyright (C) 2001-2014 NLTK Project
# Author: Edward Loper <edloper@gmail.com>
# URL: <http://nltk.org/>
# For license information, see LICENSE.TXT

"""
An NLTK interface to the VerbNet verb lexicon

For details about VerbNet see:
http://verbs.colorado.edu/~mpalmer/projects/verbnet.html
"""
from __future__ import unicode_literals

import re
import textwrap
from collections import defaultdict
from xml.etree import ElementTree as ET

from nltk import compat
from nltk.corpus.reader.xmldocs import XMLCorpusReader


class VerbNetError(Exception):
    """An exception class for wordnet-related errors."""


class VerbnetCorpusReader(XMLCorpusReader):

    # No unicode encoding param, since the data files are all XML.
    def __init__(self, root, fileids, wrap_etree=False):
        XMLCorpusReader.__init__(self, root, fileids, wrap_etree)

        self.expand_substructures = 'verbenet' in str(root)

        self._lemma_to_class = defaultdict(list)
        """A dictionary mapping from verb lemma strings to lists of
        VerbNet class identifiers."""

        self._wordnet_to_class = defaultdict(list)
        """A dictionary mapping from wordnet identifier strings to
        lists of VerbNet class identifiers."""

        self._class_to_fileid = {}
        """A dictionary mapping from class identifiers to
        corresponding file identifiers.  The keys of this dictionary
        provide a complete list of all classes and subclasses."""

        self._shortid_to_longid = {}

        # Initialize the dictionaries.  Use the quick (regexp-based)
        # method instead of the slow (xml-based) method, because it
        # runs 2-30 times faster.
        self._index()

    _LONGID_RE = re.compile(r'([^\-\.]*)-([\d+.\-]+)$')
    """Regular expression that matches (and decomposes) longids"""

    _SHORTID_RE = re.compile(r'[\d+.\-]+$')
    """Regular expression that matches shortids"""

    _INDEX_RE = re.compile(r'<MEMBER name="\??([^"]+)" wn="([^"]*)"[^>]+>|'
                           r'<VNSUBCLASS ID="([^"]+)"/?>')
    """Regular expression used by ``_index()`` to quickly scan the corpus
       for basic information."""

    def lemmas(self, classid=None):
        """
        Return a list of all verb lemmas that appear in any class, or
        in the ``classid`` if specified.
        """
        if classid is None:
            return sorted(self._lemma_to_class.keys())
        else:
            # [xx] should this include subclass members?
            vnclass = self.vnclass(classid)
            return [member.get('name') for member in
                    vnclass.findall('MEMBERS/MEMBER')]

    def wordnetids(self, classid=None):
        """
        Return a list of all wordnet identifiers that appear in any
        class, or in ``classid`` if specified.
        """
        if classid is None:
            return sorted(self._wordnet_to_class.keys())
        else:
            # [xx] should this include subclass members?
            vnclass = self.vnclass(classid)
            return sum([member.get('wn', '').split() for member in
                        vnclass.findall('MEMBERS/MEMBER')], [])

    def classids(self, lemma=None, wordnetid=None, fileid=None, classid=None):
        """
        Return a list of the VerbNet class identifiers.  If a file
        identifier is specified, then return only the VerbNet class
        identifiers for classes (and subclasses) defined by that file.
        If a lemma is specified, then return only VerbNet class
        identifiers for classes that contain that lemma as a member.
        If a wordnetid is specified, then return only identifiers for
        classes that contain that wordnetid as a member.  If a classid
        is specified, then return only identifiers for subclasses of
        the specified VerbNet class.
        """
        if len([x for x in [lemma, wordnetid, fileid, classid]
                if x is not None]) > 1:
            raise VerbNetError('Specify at most one of: fileid, '
                               'wordnetid, fileid, classid')
        if fileid is not None:
            return [c for (c, f) in self._class_to_fileid.items()
                    if f == fileid]
        elif lemma is not None:
            return self._lemma_to_class[lemma]
        elif wordnetid is not None:
            return self._wordnet_to_class[wordnetid]
        elif classid is not None:
            xmltree = self.vnclass(classid)
            return [subclass.get('ID') for subclass in
                    xmltree.findall('SUBCLASSES/VNSUBCLASS')]
        else:
            return sorted(self._class_to_fileid.keys())

    def vnclass(self, fileid_or_classid):
        """
        Return an ElementTree containing the xml for the specified
        VerbNet class.

        :param fileid_or_classid: An identifier specifying which class
            should be returned.  Can be a file identifier (such as
            ``'put-9.1.xml'``), or a VerbNet class identifier (such as
            ``'put-9.1'``) or a short VerbNet class identifier (such as
            ``'9.1'``).
        """
        # File identifier: just return the xml.
        if fileid_or_classid in self._fileids:
            return self.xml(fileid_or_classid)

        # Class identifier: get the xml, and find the right elt.
        classid = self.longid(fileid_or_classid)
        if classid in self._class_to_fileid:
            fileid = self._class_to_fileid[self.longid(classid)]
            tree = self.xml(fileid)
            if classid == tree.get('ID'):
                return tree
            else:
                for subclass in tree.findall('.//VNSUBCLASS'):
                    if classid == subclass.get('ID'):
                        return subclass

        raise VerbNetError('Unknown identifier %s' % fileid_or_classid)

    def frames(self, shortclassid, include_superclasses=False):
        """
        Return XML for all frames valid for that class ID.

        In VerbNet, if a verb is in subclass X-Y-Z, all frames from
        superclasses X and Y also apply. This method returns all those
        frames, not only those of the current class Z.
        """

        def powerset(iterable):
            from itertools import chain, combinations
            "powerset([1,2,3]) --> () (1,) (2,) (3,) (1,2) (1,3) (2,3) (1,2,3)"
            s = list(iterable)
            return chain.from_iterable(combinations(s, r) for r in range(len(s)+1))

        def powerset_permutations(iterable):
            from itertools import permutations
            for part in powerset(iterable):
                for reorder in permutations(part):
                    yield reorder

        def get_before_verb_and_verb(syntax):
            for part in syntax:
                yield part
                if part.tag == 'VERB':
                    break

        def get_frame_objects(syntax):
            """Return all frames objects after the verb, grouped by phrases"""
            i = 0
            verb_found = False
            while i < len(syntax):
                if syntax[i].tag == 'VERB':
                    verb_found = True
                elif verb_found:
                    if syntax[i].tag == 'PREP' and i+1 < len(syntax) and syntax[i+1].tag == 'NP':
                        yield (syntax[i], syntax[i+1])
                        i += 1
                    else:
                        yield (syntax[i],)

                i += 1

        def flatten_objects(objs):
            """Due to get_frame_objects, some objects were in tuple, others
            not. Flatten all of this."""
            for part in objs:
                if type(part) == tuple:
                    for tp in part:
                        yield tp
                else:
                    yield tp

        def expanded_frame(frame):
            syntax = frame.find('SYNTAX')
            frame_subject_and_verb = list(get_before_verb_and_verb(syntax))

            for frame_object_option in powerset_permutations(get_frame_objects(syntax)):
                import copy
                next_frame = copy.deepcopy(frame)
                next_frame.remove(next_frame.find('DESCRIPTION')) # description could be wrong
                next_frame.remove(next_frame.find('SYNTAX')) # syntax will change

                next_syntax = ET.Element('SYNTAX')
                for c in frame_subject_and_verb + list(flatten_objects(frame_object_option)):
                    next_syntax.append(c)

                next_frame.append(next_syntax)
                yield next_frame

        def merge_themroles(parent_themroles, child_themroles):
            for themrole in child_themroles:
                corresponding_parent_role = parent_themroles.find("THEMROLE[@type='{}']".format(themrole.get('type')))
                if corresponding_parent_role is not None:
                    parent_themroles.remove(corresponding_parent_role)
                    parent_themroles.append(themrole)

            return parent_themroles

        def all_frames_aux(wanted_id, vnclass, themroles):
            if include_superclasses:
                include_this_class = wanted_id.startswith(vnclass.get('ID'))
            else:
                include_this_class = wanted_id == vnclass.get('ID')

            if include_this_class:
                for frame in vnclass.findall('FRAMES/FRAME'):
                    if self.expand_substructures:
                        for ex_frame in expanded_frame(frame):
                            yield ex_frame, themroles
                    else:
                        yield frame, themroles

            for vnsubclass in vnclass.findall('SUBCLASSES/VNSUBCLASS'):
                subthemroles = merge_themroles(themroles, vnsubclass.find('THEMROLES'))
                # In Python 3.4, `yield from` would have been enough
                for frame, themroles in all_frames_aux(wanted_id, vnsubclass, subthemroles):
                    yield frame, themroles

        classid = self.longid(shortclassid)
        if not classid in self._class_to_fileid:
            return VerbNetError('Unknown identifier %s' % classid)

        fileid = self._class_to_fileid[self.longid(classid)]
        vnclass = self.xml(fileid)
        # In Python 3.4, `yield from` would have been enough
        for frame, themroles in all_frames_aux(shortclassid, vnclass, vnclass.find('THEMROLES')):
            yield {'frame': frame, 'themroles': themroles}

    def frames_for_lemma(self, lemma):
        for classid in self.classids(lemma):
            for frame in self.frames(classid, include_superclasses=True):
                frame['classid'] = classid
                yield frame

    def fileids(self, vnclass_ids=None):
        """
        Return a list of fileids that make up this corpus.  If
        ``vnclass_ids`` is specified, then return the fileids that make
        up the specified VerbNet class(es).
        """
        if vnclass_ids is None:
            return self._fileids
        elif isinstance(vnclass_ids, compat.string_types):
            return [self._class_to_fileid[self.longid(vnclass_ids)]]
        else:
            return [self._class_to_fileid[self.longid(vnclass_id)]
                    for vnclass_id in vnclass_ids]

    #
    # Index Initialization
    #

    def _index(self):
        """
        Initialize the indexes ``_lemma_to_class``,
        ``_wordnet_to_class``, and ``_class_to_fileid`` by scanning
        through the corpus fileids.  This is fast with cElementTree
        (<0.1 secs), but quite slow (>10 secs) with the python
        implementation of ElementTree.
        """
        for fileid in self._fileids:
            self._index_helper(self.xml(fileid), fileid)

    def _index_helper(self, xmltree, fileid):
        """Helper for ``_index()``"""
        vnclass = xmltree.get('ID')
        self._class_to_fileid[vnclass] = fileid
        self._shortid_to_longid[self.shortid(vnclass)] = vnclass
        for member in xmltree.findall('MEMBERS/MEMBER'):
            self._lemma_to_class[member.get('name')].append(vnclass)
            for wn in member.get('wn', '').split():
                self._wordnet_to_class[wn].append(vnclass)
        for subclass in xmltree.findall('SUBCLASSES/VNSUBCLASS'):
            self._index_helper(subclass, fileid)

    def _quick_index(self):
        """
        Initialize the indexes ``_lemma_to_class``,
        ``_wordnet_to_class``, and ``_class_to_fileid`` by scanning
        through the corpus fileids.  This doesn't do proper xml parsing,
        but is good enough to find everything in the standard VerbNet
        corpus -- and it runs about 30 times faster than xml parsing
        (with the python ElementTree; only 2-3 times faster with
        cElementTree).
        """
        # nb: if we got rid of wordnet_to_class, this would run 2-3
        # times faster.
        for fileid in self._fileids:
            vnclass = fileid[:-4]  # strip the '.xml'
            self._class_to_fileid[vnclass] = fileid
            self._shortid_to_longid[self.shortid(vnclass)] = vnclass
            for m in self._INDEX_RE.finditer(self.open(fileid).read()):
                groups = m.groups()
                if groups[0] is not None:
                    self._lemma_to_class[groups[0]].append(vnclass)
                    for wn in groups[1].split():
                        self._wordnet_to_class[wn].append(vnclass)
                elif groups[2] is not None:
                    self._class_to_fileid[groups[2]] = fileid
                    vnclass = groups[2]  # for <MEMBER> elts.
                    self._shortid_to_longid[self.shortid(vnclass)] = vnclass
                else:
                    assert False, 'unexpected match condition'
    #
    # Identifier conversion
    #

    def longid(self, shortid):
        """Given a short VerbNet class identifier (eg '37.10'), map it
        to a long id (eg 'confess-37.10').  If ``shortid`` is already a
        long id, then return it as-is"""
        if self._LONGID_RE.match(shortid):
            return shortid  # it's already a longid.
        elif not self._SHORTID_RE.match(shortid):
            raise VerbNetError('vnclass identifier %r not found' % shortid)
        try:
            return self._shortid_to_longid[shortid]
        except KeyError:
            raise VerbNetError('vnclass identifier %r not found' % shortid)

    def shortid(self, longid):
        """Given a long VerbNet class identifier (eg 'confess-37.10'),
        map it to a short id (eg '37.10').  If ``longid`` is already a
        short id, then return it as-is."""
        if self._SHORTID_RE.match(longid):
            return longid  # it's already a shortid.
        m = self._LONGID_RE.match(longid)
        if m:
            return m.group(2)
        else:
            raise VerbNetError('vnclass identifier %r not found' % longid)

    #
    # Pretty Printing
    #

    def pprint(self, vnclass):
        """
        Return a string containing a pretty-printed representation of
        the given VerbNet class.

        :param vnclass: A VerbNet class identifier; or an ElementTree
        containing the xml contents of a VerbNet class.
        """
        if isinstance(vnclass, compat.string_types):
            vnclass = self.vnclass(vnclass)

        s = vnclass.get('ID') + '\n'
        s += self.pprint_subclasses(vnclass, indent='  ') + '\n'
        s += self.pprint_members(vnclass, indent='  ') + '\n'
        s += '  Thematic roles:\n'
        s += self.pprint_themroles(vnclass, indent='    ') + '\n'
        s += '  Frames:\n'
        s += '\n'.join(self.pprint_frame(vnframe, indent='    ')
                       for vnframe in vnclass.findall('FRAMES/FRAME'))
        return s

    def pprint_subclasses(self, vnclass, indent=''):
        """
        Return a string containing a pretty-printed representation of
        the given VerbNet class's subclasses.

        :param vnclass: A VerbNet class identifier; or an ElementTree
            containing the xml contents of a VerbNet class.
        """
        if isinstance(vnclass, compat.string_types):
            vnclass = self.vnclass(vnclass)

        subclasses = [subclass.get('ID') for subclass in
                      vnclass.findall('SUBCLASSES/VNSUBCLASS')]
        if not subclasses:
            subclasses = ['(none)']
        s = 'Subclasses: ' + ' '.join(subclasses)
        return textwrap.fill(s, 70, initial_indent=indent,
                             subsequent_indent=indent+'  ')

    def pprint_members(self, vnclass, indent=''):
        """
        Return a string containing a pretty-printed representation of
        the given VerbNet class's member verbs.

        :param vnclass: A VerbNet class identifier; or an ElementTree
            containing the xml contents of a VerbNet class.
        """
        if isinstance(vnclass, compat.string_types):
            vnclass = self.vnclass(vnclass)

        members = [member.get('name') for member in
                   vnclass.findall('MEMBERS/MEMBER')]
        if not members:
            members = ['(none)']
        s = 'Members: ' + ' '.join(members)
        return textwrap.fill(s, 70, initial_indent=indent,
                             subsequent_indent=indent+'  ')

    def pprint_themroles(self, vnclass, indent=''):
        """
        Return a string containing a pretty-printed representation of
        the given VerbNet class's thematic roles.

        :param vnclass: A VerbNet class identifier; or an ElementTree
            containing the xml contents of a VerbNet class.
        """
        if isinstance(vnclass, compat.string_types):
            vnclass = self.vnclass(vnclass)

        pieces = []
        for themrole in vnclass.findall('THEMROLES/THEMROLE'):
            piece = indent + '* ' + themrole.get('type')
            modifiers = ['%(Value)s%(type)s' % restr.attrib
                         for restr in themrole.findall('SELRESTRS/SELRESTR')]
            if modifiers:
                piece += '[%s]' % ' '.join(modifiers)
            pieces.append(piece)

        return '\n'.join(pieces)

    def pprint_frame(self, vnframe, indent=''):
        """
        Return a string containing a pretty-printed representation of
        the given VerbNet frame.

        :param vnframe: An ElementTree containing the xml contents of
            a VerbNet frame.
        """
        s = self.pprint_description(vnframe, indent) + '\n'
        s += self.pprint_syntax(vnframe, indent+'  Syntax: ') + '\n'
        s += indent + '  Semantics:\n'
        s += self.pprint_semantics(vnframe, indent+'    ')
        return s

    def pprint_description(self, vnframe, indent=''):
        """
        Return a string containing a pretty-printed representation of
        the given VerbNet frame description.

        :param vnframe: An ElementTree containing the xml contents of
            a VerbNet frame.
        """
        descr = vnframe.find('DESCRIPTION')
        s = indent + descr.attrib['primary']
        if descr.get('secondary', ''):
            s += ' (%s)' % descr.get('secondary')
        return s

    def pprint_syntax(self, vnframe, indent=''):
        """
        Return a string containing a pretty-printed representation of
        the given VerbNet frame syntax.

        :param vnframe: An ElementTree containing the xml contents of
            a VerbNet frame.
        """
        pieces = []
        for elt in vnframe.find('SYNTAX'):
            piece = elt.tag
            modifiers = []
            if 'value' in elt.attrib:
                modifiers.append(elt.get('value'))
            modifiers += ['%(Value)s%(type)s' % restr.attrib
                          for restr in (elt.findall('SELRESTRS/SELRESTR') +
                                        elt.findall('SYNRESTRS/SYNRESTR'))]
            if modifiers:
                piece += '[%s]' % ' '.join(modifiers)
            pieces.append(piece)

        return indent + ' '.join(pieces)

    def pprint_semantics(self, vnframe, indent=''):
        """
        Return a string containing a pretty-printed representation of
        the given VerbNet frame semantics.

        :param vnframe: An ElementTree containing the xml contents of
            a VerbNet frame.
        """
        pieces = []
        for pred in vnframe.findall('SEMANTICS/PRED'):
            args = [arg.get('value') for arg in pred.findall('ARGS/ARG')]
            pieces.append('%s(%s)' % (pred.get('value'), ', '.join(args)))
        return '\n'.join('%s* %s' % (indent, piece) for piece in pieces)
