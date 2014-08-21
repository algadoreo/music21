# -*- coding: utf-8 -*-
#-------------------------------------------------------------------------------
# Name:         realizer.py
# Purpose:      music21 class to define a figured bass line, consisting of notes
#                and figures in a given key.
# Authors:      Jose Cabal-Ugaz
#
# Copyright:    Copyright © 2011 Michael Scott Cuthbert and the music21 Project
# License:      LGPL, see license.txt
#-------------------------------------------------------------------------------
'''
This module, the heart of fbRealizer, is all about realizing a bass line of (bassNote, notationString)
pairs. All it takes to create well-formed realizations of a bass line is a few lines of music21 code, 
from start to finish. See :class:`~music21.figuredBass.realizer.FiguredBassLine` for more details.

>>> from music21.figuredBass import realizer
>>> from music21 import note
>>> fbLine = realizer.FiguredBassLine()
>>> fbLine.addElement(note.Note('C3'))
>>> fbLine.addElement(note.Note('D3'), '4,3')
>>> fbLine.addElement(note.Note('C3', quarterLength = 2.0))
>>> allSols = fbLine.realize()
>>> allSols.getNumSolutions()
30
>>> #_DOCS_SHOW allSols.generateRandomRealizations(14).show()

    .. image:: images/figuredBass/fbRealizer_intro.*
        :width: 500
        

The same can be accomplished by taking the notes and notations from a :class:`~music21.stream.Stream`.
See :meth:`~music21.figuredBass.realizer.figuredBassFromStream` for more details.


>>> from music21 import tinyNotation
>>> s = tinyNotation.TinyNotationStream("C4 D4_4,3 C2")
>>> fbLine = realizer.figuredBassFromStream(s)
>>> allSols2 = fbLine.realize()
>>> allSols2.getNumSolutions()
30
'''

import collections
import copy
import random
import unittest


from music21 import chord
from music21 import clef
from music21 import environment
from music21 import exceptions21
from music21 import key
from music21 import meter
from music21 import note
from music21 import pitch
from music21 import stream
from music21.figuredBass import checker
from music21.figuredBass import notation
from music21.figuredBass import realizerScale
from music21.figuredBass import rules
from music21.figuredBass import segment
from music21.ext import six

ifilter = six.moves.filter # @UndefinedVariable

_MOD = 'realizer.py'

def figuredBassFromStream(streamPart):
    '''
    Takes a :class:`~music21.stream.Part` (or another :class:`~music21.stream.Stream` subclass) 
    and returns a :class:`~music21.figuredBass.realizer.FiguredBassLine` object whose bass notes 
    have notations taken from the lyrics in the source stream. This method along with the
    :meth:`~music21.figuredBass.realizer.FiguredBassLine.realize` method provide the easiest 
    way of converting from a notated version of a figured bass (such as in a MusicXML file) to 
    a realized version of the same line.
    
    >>> s = tinyNotation.TinyNotationStream('4/4 C4 D8_6 E8_6 F4 G4_7 c1')
    >>> fb = figuredBass.realizer.figuredBassFromStream(s)
    >>> fbRules = figuredBass.rules.Rules()
    >>> fbRules.partMovementLimits = [(1,2),(2,12),(3,12)]
    >>> fbRealization = fb.realize(fbRules)
    >>> fbRealization.getNumSolutions()
    13
    >>> #_DOCS_SHOW fbRealization.generateRandomRealizations(8).show()
    
    .. image:: images/figuredBass/fbRealizer_fbStreamPart.*
        :width: 500
            
    '''
    if streamPart.hasPartLikeStreams():
        sf = streamPart.parts[-1].flat # For a score with multiple parts, assume bass part is last part
    else:
        sf = streamPart.flat
    sfn = sf.notesAndRests

    keyList = sf.getElementsByClass(key.Key)
    myKey = None
    if len(keyList) == 0:
        keyList = sf.getElementsByClass(key.KeySignature)
        if len(keyList) == 0:
            myKey = key.Key('C')
        else:
            if keyList[0].pitchAndMode[1] is None:
                mode = 'major'
            else:
                mode = keyList[0].pitchAndMode[1]
            myKey = key.Key(keyList[0].pitchAndMode[0], mode)
    else:
        myKey = keyList[0]

    tsList = sf.getElementsByClass(meter.TimeSignature)
    if len(tsList) == 0:
        ts = meter.TimeSignature('4/4')
    else:
        ts = tsList[0]
    
    fb = FiguredBassLine(myKey, ts)
    if streamPart.hasMeasures():
        paddingLeft = streamPart.measure(0).paddingLeft
        if paddingLeft != 0.0:
            fb._paddingLeft = paddingLeft
    
    for n in sfn:
        if len(n.lyrics) > 0:
            annotationString = ", ".join([x.text for x in n.lyrics])
            # fb.addElement(n, annotationString)
            fb.fbAppend(n, annotationString) # customized version of addElement
            
        else:
            # fb.addElement(n)
            fb.fbAppend(n) # customized version of addElement
    
    return fb

def figuredBassFromStreamPart(streamPart):
    '''
    Deprecated. Use :meth:`~music21.figuredBass.realizer.figuredBassFromStream` instead.
    '''
    _environRules = environment.Environment(_MOD)
    _environRules.warn("The method figuredBassFromStreamPart() is deprecated. Use figuredBassFromStream().", DeprecationWarning)
    return figuredBassFromStream(streamPart)
    
def addLyricsToBassNote(bassNote, notationString = None):
    '''
    Takes in a bassNote and a corresponding notationString as arguments. 
    Adds the parsed notationString as lyrics to the bassNote, which is 
    useful when displaying the figured bass in external software.
    
    >>> from music21.figuredBass import realizer
    >>> from music21 import note
    >>> n1 = note.Note('G3')
    >>> realizer.addLyricsToBassNote(n1, "6,4")
    >>> n1.lyrics[0].text
    '6'
    >>> n1.lyrics[1].text
    '4'
    >>> #_DOCS_SHOW n1.show()
    
    .. image:: images/figuredBass/fbRealizer_lyrics.*
        :width: 100
    '''
    bassNote.lyrics = []
    n = notation.Notation(notationString)
    if len(n.figureStrings) == 0:
        return
    maxLength = 0
    for fs in n.figureStrings:
        if len(fs) > maxLength:
            maxLength = len(fs)
    for fs in n.figureStrings:
        spacesInFront = ''
        for i in range(maxLength - len(fs)):
            spacesInFront += ' '
        bassNote.addLyric(spacesInFront + fs, applyRaw = True)


class FiguredBassLine(object):
    '''
    A FiguredBassLine is an interface for realization of a line of (bassNote, notationString) pairs.
    Currently, only 1:1 realization is supported, meaning that every bassNote is realized and the 
    :attr:`~music21.note.GeneralNote.quarterLength` or duration of a realization above a bassNote 
    is identical to that of the bassNote.


    `inKey` defaults to C major.
    
    `inTime` defaults to 4/4.

    >>> from music21.figuredBass import realizer
    >>> from music21 import key
    >>> from music21 import meter
    >>> fbLine = realizer.FiguredBassLine(key.Key('B'), meter.TimeSignature('3/4'))
    >>> fbLine.inKey
    <music21.key.Key of B major>
    >>> fbLine.inTime
    <music21.meter.TimeSignature 3/4>
    '''
    _DOC_ORDER = ['addElement', 'fbAppend', 'generateBassLine', 'realize']
    _DOC_ATTR = {'inKey': 'A :class:`~music21.key.Key` which implies a scale value, scale mode, and key signature for a :class:`~music21.figuredBass.realizerScale.FiguredBassScale`.',
                 'inTime': 'A :class:`~music21.meter.TimeSignature` which specifies the time signature of realizations outputted to a :class:`~music21.stream.Score`.'}    
    
    def __init__(self, inKey = None, inTime=None):
        if inKey is None:
            inKey = key.Key('C')
        if inTime is None:
            inTime = meter.TimeSignature('4/4')
        
        self.inKey = inKey
        self.inTime = inTime
        self._paddingLeft = 0.0
        self._overlayedParts = stream.Part()
        self._fbScale = realizerScale.FiguredBassScale(inKey.pitchFromDegree(1), inKey.mode)
        self._fbList = []
    
    def addElement(self, bassObject, notationString = None):
        '''
        Use this method to add (bassNote, notationString) pairs to the bass line. Elements
        are realized in the order they are added.
        
        
        >>> from music21.figuredBass import realizer
        >>> from music21 import key
        >>> from music21 import meter
        >>> from music21 import note
        >>> fbLine = realizer.FiguredBassLine(key.Key('B'), meter.TimeSignature('3/4'))
        >>> fbLine.addElement(note.Note('B2'))
        >>> fbLine.addElement(note.Note('C#3'), "6")
        >>> fbLine.addElement(note.Note('D#3'), "6")
        >>> #_DOCS_SHOW fbLine.generateBassLine().show()
        
        .. image:: images/figuredBass/fbRealizer_bassLine.*
            :width: 200
            
        OMIT_FROM_DOCS    
        >>> fbLine = realizer.FiguredBassLine(key.Key('C'), meter.TimeSignature('4/4'))
        >>> fbLine.addElement(harmony.ChordSymbol('C'))
        >>> fbLine.addElement(harmony.ChordSymbol('G'))
        
        >>> fbLine = realizer.FiguredBassLine(key.Key('C'), meter.TimeSignature('4/4'))
        >>> fbLine.addElement(roman.RomanNumeral('I'))
        >>> fbLine.addElement(roman.RomanNumeral('V'))
        '''
        bassObject.notationString = notationString
        c = bassObject.classes
        #!---------- Added ability to parse rests ----------!
        if 'Note' or 'Rest' in c:
            self._fbList.append((bassObject, notationString)) #a bass note, and a notationString
            addLyricsToBassNote(bassObject, notationString) 
        #!---------- Added to accommodate harmony.ChordSymbol and roman.RomanNumeral objects --------!     
        elif 'RomanNumeral' in c or 'ChordSymbol' in c: #and item.isClassOrSubclass(harmony.Harmony):
            self._fbList.append(bassObject) #a roman Numeral object
        else:
            raise FiguredBassLineException("Not a valid bassObject (only note.Note, harmony.ChordSymbol, and roman.RomanNumeral supported) was %r" % bassObject)
    
    def fbAppend(self, bassObject, notationString = None):
        '''
        The same as addElement above, except without the call to addLyricsToBassNote which resets
        all the formatting in the lyrics line.
        
        Inserted and customized by Jason Leung, June 2014
        '''
        bassObject.notationString = notationString
        c = bassObject.classes
        #!---------- Added ability to parse rests ----------!
        if 'Note' or 'Rest' in c:
            self._fbList.append((bassObject, notationString)) #a bass note, and a notationString
        #!---------- Added to accommodate harmony.ChordSymbol and roman.RomanNumeral objects --------!     
        elif 'RomanNumeral' in c or 'ChordSymbol' in c: #and item.isClassOrSubclass(harmony.Harmony):
            self._fbList.append(bassObject) #a roman Numeral object
        else:
            raise FiguredBassLineException("Not a valid bassObject (only note.Note, harmony.ChordSymbol, and roman.RomanNumeral supported) was %r" % bassObject)

    def generateBassLine(self):
        '''
        Generates the bass line as a :class:`~music21.stream.Score`.
        
        >>> from music21.figuredBass import realizer
        >>> from music21 import key
        >>> from music21 import meter
        >>> from music21 import note
        >>> fbLine = realizer.FiguredBassLine(key.Key('B'), meter.TimeSignature('3/4'))
        >>> fbLine.addElement(note.Note('B2'))
        >>> fbLine.addElement(note.Note('C#3'), "6")
        >>> fbLine.addElement(note.Note('D#3'), "6")
        >>> #_DOCS_SHOW fbLine.generateBassLine().show()
        
        .. image:: images/figuredBass/fbRealizer_bassLine.*
            :width: 200
           
            
        >>> from music21 import corpus
        >>> sBach = corpus.parse('bach/bwv307')
        >>> sBach['bass'].measure(0).show("text")
        {0.0} <music21.clef.BassClef>
        {0.0} <music21.key.KeySignature of 2 flats, mode major>
        {0.0} <music21.meter.TimeSignature 4/4>
        {0.0} <music21.note.Note B->
        {0.5} <music21.note.Note C>
        >>> fbLine = realizer.figuredBassFromStream(sBach['bass'])
        >>> fbLine.generateBassLine().measure(1).show("text")
        {0.0} <music21.clef.BassClef>
        {0.0} <music21.key.KeySignature of 2 flats>
        {0.0} <music21.meter.TimeSignature 4/4>
        {3.0} <music21.note.Note B->
        {3.5} <music21.note.Note C>
        '''
        bassLine = stream.Part()
        bassLine.append(copy.deepcopy(self.inTime))
        bassLine.append(key.KeySignature(self.inKey.sharps))
        bassLine.append(clef.BassClef())
        r = None
        if self._paddingLeft != 0.0:
            r = note.Rest(quarterLength = self._paddingLeft)
            bassLine.append(r)
        for (bassNote, unused_notationString) in self._fbList:
            bassLine.append(bassNote)
        
        bassLine.makeNotation(inPlace=True, cautionaryNotImmediateRepeat=False)
        if r is not None:
            bassLine[0].pop(3)
            bassLine[0].padAsAnacrusis()
        return bassLine
    
    def retrieveSegments(self, fbRules = None, numParts = 4, maxPitch = None, harmonicBeat = 1.0, extensionString = ''):
        '''
        generates the segmentList from an fbList, including any overlayed Segments

        if fbRules is None, creates a new rules.Rules() object
        
        if maxPitch is None, uses pitch.Pitch('B5')

        the harmonic beat (when chord changes usually happen) is a quarter note by default

        an extension will be output as an empty string by default
        '''
        if fbRules is None:
            fbRules = rules.Rules()
        if maxPitch is None:
            maxPitch = pitch.Pitch('B5')
        segmentList = []
        bassLine = self.generateBassLine()
        if len(self._overlayedParts) >= 1:
            self._overlayedParts.append(bassLine)
            currentMapping = checker.extractHarmonies(self._overlayedParts)
        else:
            currentMapping = checker.createOffsetMapping(bassLine)
        allKeys = sorted(currentMapping.keys())
        bassLine = bassLine.flat.notesAndRests
        bassNoteIndex = 0
        previousBassNote = bassLine[bassNoteIndex]
        bassNote = currentMapping[allKeys[0]][-1]
        previousSegment = segment.OverlayedSegment(bassNote, bassNote.notationString, self._fbScale,\
                                                   fbRules, numParts, maxPitch)
        previousSegment.quarterLength = previousBassNote.quarterLength
        segmentList.append(previousSegment)
        for k in allKeys[1:]:
            (startTime, unused_endTime) = k
            bassNote = currentMapping[k][-1]
            currentSegment = segment.OverlayedSegment(bassNote, bassNote.notationString, self._fbScale,\
                                                      fbRules, numParts, maxPitch)
            for partNumber in range(1, len(currentMapping[k])):
                upperPitch = currentMapping[k][partNumber-1]
                currentSegment.fbRules._partPitchLimits.append((partNumber, upperPitch))
            if startTime == previousBassNote.offset + previousBassNote.quarterLength:
                bassNoteIndex+=1
                previousBassNote = bassLine[bassNoteIndex]
                currentSegment.quarterLength = previousBassNote.quarterLength
            else:
                for partNumber in range(len(currentMapping[k]), numParts+1):
                    previousSegment.fbRules._partsToCheck.append(partNumber)
                currentSegment.quarterLength = 0.0 # Fictitious, representative only for harmonies preserved with addition of melody or melodies

            #!---------- Check to see if this note is a complete extension (whole chord extended/tied); yes by default ----------!
            extendAll = True
            if not bassNote.lyrics:
                extendAll = False
            else:
                for l in bassNote.lyrics:
                    #!---------- If there is non-extension (i.e., a numeral/accidental), then it is not a complete extension ----------!
                    if l.syllabic != 'end':
                        extendAll = False
                        break

            #!---------- Provision to take care of extensions, passing/neighbour notes etc, and ties ----------!
            if extendAll or (startTime % harmonicBeat != 0.0 and not bassNote.lyrics) or (bassNote.tie and (bassNote.tie.type == 'stop' or bassNote.tie.type == 'continue') and not bassNote.lyrics):
                previousSegment.quarterLength += bassNote.quarterLength
            #!---------- Original code below; advance chord only if on a harmonic beat or has figured bass ----------!
            else:
                segmentList.append(currentSegment)
                previousSegment = currentSegment

            #!---------- Aesthetics: mark extensions with dash ----------!
            for l in bassNote.lyrics:
                if l.syllabic == 'end':
                    l.text = extensionString

        return (bassLine, segmentList)
    
    def overlayPart(self, music21Part):
        self._overlayedParts.append(music21Part)
        
    def realize(self, fbRules = None, numParts = 4, maxPitch = None, harmonicBeat = 1.0, extensionString = ''):
        '''
        Creates a :class:`~music21.figuredBass.segment.Segment` for each (bassNote, notationString) pair
        added using :meth:`~music21.figuredBass.realizer.FiguredBassLine.addElement`. Each Segment is associated
        with the :class:`~music21.figuredBass.rules.Rules` object provided, meaning that rules are
        universally applied across all Segments. The number of parts in a realization
        (including the bass) can be controlled through numParts, and the maximum pitch can
        likewise be controlled through maxPitch. Returns a :class:`~music21.figuredBass.realizer.Realization`.
        
        
        If this methods is called without having provided any (bassNote, notationString) pairs,
        a FiguredBassLineException is raised. If only one pair is provided, the Realization will
        contain :meth:`~music21.figuredBass.segment.Segment.allCorrectConsecutivePossibilities`
        for the one note.

        if `fbRules` is None, creates a new rules.Rules() object
        
        if `maxPitch` is None, uses pitch.Pitch('B5')

        'harmonicBeat' added by Jason Leung, June 2014
        Refers to the default unit of harmonic time (when chord changes usually happen), measured in quarterLength

        'extensionString' added by Jason Leung, June 2014
        Is the string used to mark extensions on the output score. Default is empty string, but oftentimes '-' (a
        dash) is used.

        
        
        >>> from music21.figuredBass import realizer
        >>> from music21.figuredBass import rules
        >>> from music21 import key
        >>> from music21 import meter
        >>> from music21 import note
        >>> fbLine = realizer.FiguredBassLine(key.Key('B'), meter.TimeSignature('3/4'))
        >>> fbLine.addElement(note.Note('B2'))
        >>> fbLine.addElement(note.Note('C#3'), "6")
        >>> fbLine.addElement(note.Note('D#3'), "6")
        >>> fbRules = rules.Rules()
        >>> r1 = fbLine.realize(fbRules)
        >>> r1.getNumSolutions()
        208
        >>> fbRules.forbidVoiceOverlap = False
        >>> r2 = fbLine.realize(fbRules)
        >>> r2.getNumSolutions()
        7908
        
        OMIT_FROM_DOCS
        >>> fbLine3 = realizer.FiguredBassLine(key.Key('C'), meter.TimeSignature('2/4'))
        >>> h1 = harmony.ChordSymbol('C')
        >>> h1.bass().octave = 4
        >>> fbLine3.addElement(h1)
        >>> h2 = harmony.ChordSymbol('G')
        >>> h2.bass().octave = 4
        >>> fbLine3.addElement(h2)
        >>> r3 = fbLine3.realize()
        >>> r3.getNumSolutions()
        13
        >>> fbLine4 = realizer.FiguredBassLine(key.Key('C'), meter.TimeSignature('2/4'))
        >>> fbLine4.addElement(roman.RomanNumeral('I'))
        >>> fbLine4.addElement(roman.RomanNumeral('IV'))
        >>> r4 = fbLine4.realize()
        >>> r4.getNumSolutions()
        13

        '''
        if fbRules is None:
            fbRules = rules.Rules()
        if maxPitch is None:
            maxPitch = pitch.Pitch('B5')
                    
        segmentList = []

        listOfHarmonyObjects = False
        for item in self._fbList:
            try:
                c = item.classes
            except AttributeError:
                continue
            if 'Note' or 'Rest' in c:
                break
            #!---------- Added to accommodate harmony.ChordSymbol and roman.RomanNumeral objects --------!
            if 'RomanNumeral' in c or 'ChordSymbol' in c: #and item.isClassOrSubclass(harmony.Harmony):
                listOfHarmonyObjects = True
                break
            
        if listOfHarmonyObjects:
            for harmonyObject in self._fbList:                
                listofpitchesjustnames = []
                for thisPitch in harmonyObject.pitches:
                    listofpitchesjustnames.append(thisPitch.name)
                #remove duplicates just in case...
                d = {}
                for x in listofpitchesjustnames: 
                    d[x]=x
                outputList = d.values()    
                g = lambda x: x if x != 0.0 else 1.0
                passedNote = note.Note(harmonyObject.bass().nameWithOctave , quarterLength = g(harmonyObject.duration.quarterLength) )
                correspondingSegment = segment.Segment(bassNote=passedNote, \
                fbScale=self._fbScale, fbRules=fbRules, numParts=numParts, maxPitch=maxPitch, listOfPitches=outputList)
                correspondingSegment.quarterLength = g(harmonyObject.duration.quarterLength)
                segmentList.append(correspondingSegment)                
        #!---------- Original code - Accommodates a tuple (figured bass)  --------!
        else:
            (bassLine, segmentList) = self.retrieveSegments(fbRules, numParts, maxPitch, harmonicBeat, extensionString)      

        if len(segmentList) >= 2 and len(bassLine.flat.notes) >= 2:
            for segmentIndex in range(len(segmentList) - 1):
                segmentA = segmentList[segmentIndex]
                if segmentA.segmentChord.isRest:
                #!---------- Added code: if it's a rest, don't look for resolution and continue to next note/segment ----------!
                    continue
                #!---------- Added code: look for the following note/segment ----------!
                i = 1
                while segmentIndex + i < len(segmentList) and segmentList[segmentIndex + i].segmentChord.isRest:
                    i += 1
                if segmentIndex + i >= len(segmentList):
                    break
                segmentB = segmentList[segmentIndex + i]
                correctAB = segmentA.allCorrectConsecutivePossibilities(segmentB)
                segmentA.movements = collections.defaultdict(list)
                listAB = list(correctAB)
                for (possibA, possibB) in listAB:
                    segmentA.movements[possibA].append(possibB)
            self._trimAllMovements(segmentList)
        elif len(segmentList) == 1:
            segmentA = segmentList[0]
            segmentA.correctA = list(segmentA.allCorrectSinglePossibilities())
        elif len(bassLine.flat.notes) == 1:
            #!---------- This is for when there is only one note, but surrounded by rests; find the note/chord ('segment') and return its realization ----------!
            for segmentA in segmentList:
                try:
                    segmentA.correctA = list(segmentA.allCorrectSinglePossibilities())
                    break
                except:
                    continue
        elif len(segmentList) == 0 or len(bassLine.flat.notes) == 0:
            raise FiguredBassLineException("No (bassNote, notationString) pairs to realize.")

        return Realization(realizedSegmentList = segmentList, inKey = self.inKey, 
                           inTime = self.inTime, overlayedParts = self._overlayedParts[0:-1],
                           paddingLeft = self._paddingLeft, bassLine = bassLine)

    def generateRandomRealization(self):         
        '''
        Generates a random realization of a figured bass as a :class:`~music21.stream.Score`, 
        with the default rules set **and** a soprano line limited to stepwise motion.
        
        
        .. note:: Deprecated. Use :meth:`~music21.figuredBass.realizer.FiguredBassLine.realize`
            which returns a :class:`~music21.figuredBass.realizer.Realization`. Then, call :meth:`~music21.figuredBass.realizer.Realization.generateRandomRealization`.
        '''
        _environRules = environment.Environment(_MOD)
        _environRules.warn("The method generateRandomRealization() is deprecated. Use realize() instead and call generateRandomRealization() on the result.", DeprecationWarning)
        fbRules = rules.Rules()
        fbRules.partMovementLimits = [(1,2),(2,12),(3,12)]        
        return self.realize(fbRules).generateRandomRealization()

    def showRandomRealization(self):         
        '''
        Displays a random realization of a figured bass as a musicxml in external software, 
        with the default rules set **and** a soprano line limited to stepwise motion.
        
        
        .. note:: Deprecated. Use :meth:`~music21.figuredBass.realizer.FiguredBassLine.realize`
            which returns a :class:`~music21.figuredBass.realizer.Realization`. Then, call :meth:`~music21.figuredBass.realizer.Realization.generateRandomRealization`
            followed by a call to :meth:`~music21.base.Music21Object.show`.
        '''
        _environRules = environment.Environment(_MOD)
        _environRules.warn("The method showRandomRealization() is deprecated. Use realize() instead and call generateRandomRealization().show() on the result.", DeprecationWarning)
        fbRules = rules.Rules()
        fbRules.partMovementLimits = [(1,2),(2,12),(3,12)]
        return self.realize(fbRules).generateRandomRealization().show()
            
    def showAllRealizations(self):
        '''
        Displays all realizations of a figured bass as a musicxml in external software, 
        with the default rules set **and** a soprano line limited to stepwise motion.
        
        
        .. note:: Deprecated. Use :meth:`~music21.figuredBass.realizer.FiguredBassLine.realize`
            which returns a :class:`~music21.figuredBass.realizer.Realization`. Then, call :meth:`~music21.figuredBass.realizer.Realization.generateAllRealizations`
            followed by a call to :meth:`~music21.base.Music21Object.show`.
        

        .. warning:: This method is unoptimized, and may take a prohibitive amount
            of time for a Realization which has more than tens of unique realizations.
        '''
        _environRules = environment.Environment(_MOD)
        _environRules.warn("The method showAllRealizations() is deprecated. Use realize() instead and call generateAllRealizations().show() on the result.", DeprecationWarning)
        fbRules = rules.Rules()
        fbRules.partMovementLimits = [(1,2),(2,12),(3,12)]
        return self.realize(fbRules).generateAllRealizations().show()
    
    def _trimAllMovements(self, segmentList):
        '''
        Each :class:`~music21.figuredBass.segment.Segment` which resolves to another
        defines a list of movements, nextMovements. Keys for nextMovements are correct
        single possibilities of the current Segment. For a given key, a value is a list
        of correct single possibilities in the subsequent Segment representing acceptable
        movements between the two. There may be movements in a string of Segments which
        directly or indirectly lead nowhere. This method is designed to be called on
        a list of Segments **after** movements are found, as happens in 
        :meth:`~music21.figuredBass.realizer.FiguredBassLine.realize`.
        '''
        if len(segmentList) == 1 or len(segmentList) == 2:
            return True
        elif len(segmentList) >= 3:
            segmentList.reverse()
            for segmentIndex in range(1, len(segmentList) - 1):
                #!---------- Added code: check for rests ----------!
                if segmentList[segmentIndex].segmentChord.isRest:
                    continue
                i = 1
                while segmentIndex + i < len(segmentList) and segmentList[segmentIndex + i].segmentChord.isRest:
                    i += 1
                if segmentIndex + i >= len(segmentList):
                    break
                movementsAB = segmentList[segmentIndex + i].movements
                #!---------- Last note (first on this reversed list) rests doesn't have 'movements' attribute ----------!
                try:
                    #!---------- Original code below ----------!
                    movementsBC = segmentList[segmentIndex].movements
                except:
                    continue
                #eliminated = []
                for (possibB, possibCList) in list(movementsBC.items()):
                    if len(possibCList) == 0:
                        del movementsBC[possibB]
                for (possibA, possibBList) in list(movementsAB.items()):
                    movementsAB[possibA] = list(ifilter(lambda possibB: possibB in movementsBC, possibBList))

            try:
                movementsAB
                for (possibA, possibBList) in movementsAB.items():
                    if len(possibBList) == 0:
                        del movementsAB[possibA]
            except:
                pass
                    
            segmentList.reverse()
            return True

class Realization(object):
    '''
    Returned by :class:`~music21.figuredBass.realizer.FiguredBassLine` after calling
    :meth:`~music21.figuredBass.realizer.FiguredBassLine.realize`. Allows for the 
    generation of realizations as a :class:`~music21.stream.Score`.
    
    
    * See the :mod:`~music21.figuredBass.examples` module for examples on the generation
      of realizations.
    * A possibility progression is a valid progression through a string of 
      :class:`~music21.figuredBass.segment.Segment` instances.
      See :mod:`~music21.figuredBass.possibility` for more details on possibilities.
    '''
    _DOC_ORDER = ['getNumSolutions', 'generateRandomRealization', 'generateRandomRealizations', 'generateAllRealizations',
                  'getAllPossibilityProgressions', 'getRandomPossibilityProgression', 'generateRealizationFromPossibilityProgression']
    _DOC_ATTR = {'keyboardStyleOutput': '''True by default. If True, generated realizations are represented in keyboard style, with two staves. If False,
    realizations are represented in chorale style with n staves, where n is the number of parts. SATB if n = 4.'''}
    def __init__(self, **fbLineOutputs):
        # fbLineOutputs always will have three elements, checks are for sphinx documentation only.
        if 'realizedSegmentList' in fbLineOutputs:
            self._segmentList = fbLineOutputs['realizedSegmentList']
        if 'inKey' in fbLineOutputs:
            self._inKey = fbLineOutputs['inKey']
            self._keySig = key.KeySignature(self._inKey.sharps)
        if 'inTime' in fbLineOutputs:
            self._inTime = fbLineOutputs['inTime']
        if 'overlayedParts' in fbLineOutputs:
            self._overlayedParts = fbLineOutputs['overlayedParts']
        if 'paddingLeft' in fbLineOutputs:
            self._paddingLeft = fbLineOutputs['paddingLeft']
        if 'bassLine' in fbLineOutputs:
            self._bassLine = fbLineOutputs['bassLine']
        self.keyboardStyleOutput = True 

    def getNumSolutions(self):
        '''
        Returns the number of solutions (unique realizations) to a Realization by calculating
        the total number of paths through a string of :class:`~music21.figuredBass.segment.Segment`
        movements. This is faster and more efficient than compiling each unique realization into a 
        list, adding it to a master list, and then taking the length of the master list.
        
        >>> from music21.figuredBass import examples
        >>> fbLine = examples.exampleB()
        >>> fbRealization = fbLine.realize()
        >>> fbRealization.getNumSolutions()
        422
        >>> fbLine2 = examples.exampleC()
        >>> fbRealization2 = fbLine2.realize()
        >>> fbRealization2.getNumSolutions()
        833
        '''
        if len(self._segmentList) == 1:
            return len(self._segmentList[0].correctA)
        elif len(self._bassLine.flat.notes) == 1:
            #!---------- This is for when there is only one note, but surrounded by rests; find the note/chord ('segment') and return its realization ----------!
            #!---------- Possible to merge into above 'if'; separation due to authorship ----------!
            for i in self._segmentList:
                try:
                    return len(i.correctA)
                except:
                    continue
        # What if there's only one (bassNote, notationString)?
        self._segmentList.reverse()
        pathList = {}
        for segmentIndex in range(1, len(self._segmentList)):
            segmentA = self._segmentList[segmentIndex]
            if segmentA.segmentChord.isRest:
                continue
            try:
                #!---------- Last note (first on this reversed list) wouldn't have 'movements' either ----------!
                segmentA.movements
            except:
                continue
            newPathList = {}
            if len(pathList.keys()) == 0:
                for possibA in segmentA.movements:
                    newPathList[possibA] = len(segmentA.movements[possibA])
            else:
                for possibA in segmentA.movements:
                    prevValue = 0
                    for possibB in segmentA.movements[possibA]:
                        prevValue += pathList[possibB]
                    newPathList[possibA] = prevValue
            pathList = newPathList

        numSolutions = 0
        for possibA in pathList:
            numSolutions += pathList[possibA]  
        self._segmentList.reverse()
        return numSolutions
    
    def getAllPossibilityProgressions(self):
        '''
        Compiles each unique possibility progression, adding 
        it to a master list. Returns the master list.
        
        
        .. warning:: This method is unoptimized, and may take a prohibitive amount
            of time for a Realization which has more than 200,000 solutions.
        '''
        progressions = []
        if len(self._segmentList) == 1:
            for possibA in self._segmentList[0].correctA:
                progressions.append([possibA])
            return progressions
        elif len(self._bassLine.flat.notes) == 1:
            #!---------- If there is only one note, find its location (index) ----------!
            noteIndex = 0
            while noteIndex < len(self._segmentList) and self._segmentList[noteIndex].segmentChord.isRest:
                noteIndex += 1
            for possibA in self._segmentList[noteIndex].correctA:
                prog = [()]*noteIndex + [possibA]
                progressions.append(prog)
            return progressions
        
        #!---------- Find first note (in case of rests at beginning) ----------!
        firstNoteIndex = 0
        while firstNoteIndex < len(self._segmentList) and self._segmentList[firstNoteIndex].segmentChord.isRest:
            firstNoteIndex += 1
        indicesUntilSecondNote = 1
        while (firstNoteIndex + indicesUntilSecondNote) < len(self._segmentList) and self._segmentList[firstNoteIndex + indicesUntilSecondNote].segmentChord.isRest:
            indicesUntilSecondNote += 1

        currMovements = self._segmentList[firstNoteIndex].movements
        for possibA in currMovements:
            possibBList = currMovements[possibA]
            for possibB in possibBList:
                # progressions.append([possibA, possibB])
                prog = [()]*firstNoteIndex + [possibA] + [()]*(indicesUntilSecondNote-1) + [possibB]
                progressions.append(prog)

        for segmentIndex in range(firstNoteIndex+indicesUntilSecondNote, len(self._segmentList)-1):
            indicesUntilNextNote = 1
            while (segmentIndex + indicesUntilNextNote) < len(self._segmentList) and self._segmentList[segmentIndex + indicesUntilNextNote].segmentChord.isRest:
                indicesUntilNextNote += 1
            try:
                currMovements = self._segmentList[segmentIndex].movements
            except:
                continue
            for unused_progIndex in range(len(progressions)):
                prog = progressions.pop(0)
                possibB = prog[-1]
                for possibC in currMovements[possibB]:
                    newProg = copy.copy(prog)
                    # newProg.append(possibC)
                    newProg += [()]*(indicesUntilNextNote-1) + [possibC]
                    progressions.append(newProg)
        
        return progressions
    
    def getRandomPossibilityProgression(self):
        '''
        Returns a random unique possibility progression.
        '''
        progression = []
        if len(self._segmentList) == 1:
            possibA = random.sample(self._segmentList[0].correctA, 1)[0]
            progression.append(possibA)
            return progression
        elif len(self._bassLine.flat.notes) == 1:
            #!---------- This is for when there is only one note, but surrounded by rests; find the note/chord ('segment') and return its realization ----------!
            #!---------- Possible to merge into above 'if'; separation due to authorship ----------!
            for i in self._segmentList:
                try:
                    possibA = random.sample(i.correctA, 1)[0]
                except:
                    possibA = []
                progression.append(possibA)
            return progression
        
        if self.getNumSolutions() == 0:
            raise FiguredBassLineException("Zero solutions")
        #!---------- Find first note (in case of rests at beginning) ----------!
        i = 0
        while i < len(self._segmentList) and self._segmentList[i].segmentChord.isRest:
            prevPossib = []
            progression.append(prevPossib)
            i += 1
        currMovements = self._segmentList[i].movements
        prevPossib = random.sample(currMovements.keys(), 1)[0]
        progression.append(prevPossib)
        
        for segmentIndex in range(i, len(self._segmentList)-1):
            if self._segmentList[segmentIndex].segmentChord.isRest:
                progression.append(prevPossib)
            else:
                try:
                    #!---------- Last note before ending rests doesn't have 'movements' attribute ----------!
                    currMovements = self._segmentList[segmentIndex].movements
                except:
                    continue
                nextPossib = random.sample(currMovements[prevPossib], 1)[0]
                progression.append(nextPossib)
                prevPossib = nextPossib

        return progression

    def generateRealizationFromPossibilityProgression(self, possibilityProgression):
        '''
        Generates a realization as a :class:`~music21.stream.Score` given a possibility progression.        
        '''
        sol = stream.Score()
        
        bassLine = stream.Part()
        bassLine.append([copy.deepcopy(self._keySig), copy.deepcopy(self._inTime)])
        r = None
        if self._paddingLeft != 0.0:
            r = note.Rest(quarterLength = self._paddingLeft)
            bassLine.append(copy.deepcopy(r))
        
        for n in self._bassLine:
            bassLine.append(n)

        if self.keyboardStyleOutput:
            rightHand = stream.Part()
            sol.insert(0.0, rightHand)
            rightHand.append([copy.deepcopy(self._keySig), copy.deepcopy(self._inTime)])
            if r is not None:
                rightHand.append(copy.deepcopy(r))

            for segmentIndex in range(len(self._segmentList)):
                if self._segmentList[segmentIndex].segmentChord.isRest:
                    rhChord = note.Rest()
                else:
                    #! ---------- Original code ----------!
                    possibA = possibilityProgression[segmentIndex]
                    rhPitches = possibA[0:-1]
                    rhChord = chord.Chord(rhPitches)
                    rhChord.removeRedundantPitches() # Added for aesthetics
                rhChord.quarterLength = self._segmentList[segmentIndex].quarterLength
                rightHand.append(rhChord)
            rightHand.insert(0.0, clef.TrebleClef())
            
            rightHand.makeNotation(inPlace=True, cautionaryNotImmediateRepeat=False)
            if r is not None:
                rightHand[0].pop(3)
                rightHand[0].padAsAnacrusis()
                
        else: # Chorale-style output
            upperParts = []
            for partNumber in range(len(possibilityProgression[0]) - 1):
                fbPart = stream.Part()
                sol.insert(0.0, fbPart)
                fbPart.append([copy.deepcopy(self._keySig), copy.deepcopy(self._inTime)])
                if r is not None:
                    fbPart.append(copy.deepcopy(r))
                upperParts.append(fbPart)

            for segmentIndex in range(len(self._segmentList)):
                if self._segmentList[segmentIndex].segmentChord.isRest:
                    for partNumber in range(len(possibA) - 1):
                        n1 = note.Rest()
                        n1.quarterLength = self._segmentList[segmentIndex].quarterLength
                        upperParts[partNumber].append(n1)
                else:
                    #!---------- Original code ----------!
                    possibA = possibilityProgression[segmentIndex] 

                    for partNumber in range(len(possibA) - 1):
                        n1 = note.Note(possibA[partNumber])
                        n1.quarterLength = self._segmentList[segmentIndex].quarterLength
                        upperParts[partNumber].append(n1)
                    
            for upperPart in upperParts:
                upperPart.insert(0.0, upperPart.bestClef(True))
                upperPart.makeNotation(inPlace=True, cautionaryNotImmediateRepeat=False)
                if r is not None:
                    upperPart[0].pop(3)
                    upperPart[0].padAsAnacrusis()

                     
        bassLine.insert(0.0, clef.BassClef())
        bassLine.makeNotation(inPlace=True, cautionaryNotImmediateRepeat=False)
        if r is not None:
            bassLine[0].pop(3)
            bassLine[0].padAsAnacrusis()           
        sol.insert(0.0, bassLine)
        return sol

    def generateAllRealizations(self):
        '''
        Generates all unique realizations as a :class:`~music21.stream.Score`.
        
        
        .. warning:: This method is unoptimized, and may take a prohibitive amount
            of time for a Realization which has more than 100 solutions.
        '''
        allSols = stream.Score()
        possibilityProgressions = self.getAllPossibilityProgressions()
        if len(possibilityProgressions) == 0:
            raise FiguredBassLineException("Zero solutions")
        sol0 = self.generateRealizationFromPossibilityProgression(possibilityProgressions[0])
        for music21Part in sol0:
            allSols.append(music21Part)
        
        for possibIndex in range(1, len(possibilityProgressions)):
            solX = self.generateRealizationFromPossibilityProgression(possibilityProgressions[possibIndex])
            for partIndex in range(len(solX)):
                for music21Measure in solX[partIndex]:
                    allSols[partIndex].append(music21Measure)
        
        return allSols

    def generateRandomRealization(self):
        '''
        Generates a random unique realization as a :class:`~music21.stream.Score`.
        '''
        possibilityProgression = self.getRandomPossibilityProgression()
        return self.generateRealizationFromPossibilityProgression(possibilityProgression)

    def generateRandomRealizations(self, amountToGenerate = 20):
        '''
        Generates *amountToGenerate* unique realizations as a :class:`~music21.stream.Score`.
        

        .. warning:: This method is unoptimized, and may take a prohibitive amount
            of time if amountToGenerate is more than 100.
        '''
        if amountToGenerate >= self.getNumSolutions():
            return self.generateAllRealizations()
        
        allSols = stream.Score()
        sol0 = self.generateRandomRealization()
        for music21Part in sol0:
            allSols.append(music21Part)
        
        for unused_counter_solution in range(1, amountToGenerate):
            solX = self.generateRandomRealization()
            for partIndex in range(len(solX)):
                for music21Measure in solX[partIndex]:
                    allSols[partIndex].append(music21Measure)
        
        return allSols

_DOC_ORDER = [figuredBassFromStream, figuredBassFromStreamPart, addLyricsToBassNote, FiguredBassLine, Realization]

class FiguredBassLineException(exceptions21.Music21Exception):
    pass
    
#-------------------------------------------------------------------------------
class Test(unittest.TestCase):

    def runTest(self):
        pass

if __name__ == "__main__":
    import music21
    music21.mainTest(Test)

#------------------------------------------------------------------------------
# eof
