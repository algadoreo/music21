# -*- coding: utf-8 -*-
#-------------------------------------------------------------------------------
# Name:         cleaners.py
# Purpose:      classes for cleaning out autogenerated documentation files
#
# Authors:      Josiah Wolf Oberholtzer
#
# Copyright:    Copyright © 2013 Michael Scott Cuthbert and the music21 Project
# License:      LGPL or BSD, see license.txt
#-------------------------------------------------------------------------------

import os
from music21 import common


class Cleaner(object):
    '''
    Bass class for documentation cleaning classes.
    '''

    ### PUBLIC PROPERTIES ###

    @property
    def documentationSourcePath(self):
        import music21
        rootFilesystemPath = music21.__path__[0]
        return os.path.join(
            rootFilesystemPath,
            'documentation',
            'source',
            )
        
    ### PUBLIC METHODS ###

    def removeFile(self, filePath):
        if os.path.exists(filePath):
            print('\tCLEANED {0}'.format(common.relativepath(filePath)))
            os.remove(filePath)


class CorpusReferenceCleaner(Cleaner):
    '''
    Cleans the corpus reference rst file.
    '''
    def run(self):
        corpusReferencePath = os.path.join(
            self.documentationSourcePath,
            'systemReference',
            'referenceCorpus.rst',
            )
        self.removeFile(corpusReferencePath)


class IPythonNotebookCleaner(Cleaner):
    '''
    Cleans rst files generated from IPython notebooks.
    '''

    ### SPECIAL METHODS ###

    def run(self):
        for directoryPath, unused_directoryNames, fileNames in os.walk(
            self.documentationSourcePath):
            for fileName in fileNames:
                if not fileName.endswith('.ipynb'):
                    continue
                notebookFilePath = os.path.join(
                    directoryPath,
                    fileName,
                    )
                rstFilePath = notebookFilePath.replace('.ipynb', '.rst')
                self.removeFile(rstFilePath) 


class ModuleReferenceCleaner(Cleaner):
    '''
    Cleans auto-generated module reference rst files.
    '''

    ### SPECIAL METHODS ###

    def run(self):
        moduleReferencePath = os.path.join(
            self.documentationSourcePath,
            'moduleReference',
            )
        for fileName in os.listdir(moduleReferencePath):
            if fileName.startswith('module') and fileName.endswith('.rst'):
                filePath = os.path.join(
                    moduleReferencePath,
                    fileName,
                    )
            elif fileName == 'index.rst':
                filePath = os.path.join(
                    moduleReferencePath,
                    'index.rst',
                    )
            else:
                continue
            self.removeFile(filePath)


if __name__ == '__main__':
    import music21
    music21.mainTest()

