#!/usr/bin/python -u
#
#
from __future__ import absolute_import

import sys
import os
import pprint

_UP = os.path.join( os.path.split( __file__ )[0], "../.." )
sys.path.append( os.path.realpath( _UP ) )
import sas

# this parser returns a data item (tag/value pair) in one callback (loop values are matched w/ headers)
# loop terminators are implicit, so the parser "fakes" endLoop()s. There are multiple data blocks, too,
# endData()s are generated as well.
#
class Parser( sas.ParserBase ) :

    """
    Parser for STAR DDL format.

    "DDL" variant of STAR has multiple data blocks per file as well as data loops and items in
    and out of saveframes, explicit loop end markers are not required but BMRB uses them anyway.
    Note that you have to explicitly return True from ``endData()`` to stop parsing,
    unless it's the last one at EOF.

    This parser is for ``ContentHandler`` interface, see ``handlers.py`` for details.
    """

    # read a delimited value
    # returns a pair: val, stop where stop is the "stop parsing" sign
    #
    def _read_value( self, delimiter ) :
        assert isinstance( self._lexer, sas.StarLexer )
        assert delimiter in ("SINGLESTART","TSINGLESTART","DOUBLESTART","TDOUBLESTART","SEMISTART")

        if self._verbose : sys.stdout.write( self.__class__.__name__ + "._read_value(%s)\n" % (delimiter,) )

        stop = False
        val = ""
        try :
            for token in self._lexer :

                if delimiter in ("SINGLESTART","DOUBLESTART") :
                    if token.type == "NL" :
                        if self._eh.error( line = token.lineno, msg = "newline in quoted value: %s" % (val,) ) :
                            stop = True
                            break
                        val += "\n"
                        continue

                if delimiter == "SINGLESTART" :
                    if token.type == "SINGLEEND" :
                        break

                if delimiter == "DOUBLESTART" :
                    if token.type == "DOUBLEEND" :
                        break

                if delimiter == "TSINGLESTART" :
                    if token.type == "TSINGLEEND" :
                        break

                if delimiter == "TDOUBLESTART" :
                    if token.type == "TDOUBLEEND" :
                        break

# assume that trailing \n is a part of the "\n;" delimiter and strip it off
#
                if delimiter == "SEMISTART" :
                    if token.type == "SEMIEND" :
                        if val.endswith( "\n" ) : val = val.rstrip( "\n" )
                        break

                if not delimiter in ("SINGLESTART","DOUBLESTART") :
                    for pat in sas.KEYWORDS :
                        m = pat.search( token.value.strip() )
                        if m :
                            if self._eh.warning( line = token.lineno, msg = "keyword in value: %s" \
                                    % (m.group( 1 ),) ) :
                                stop = True

# stop on the 1st hit
#
                            break
                val += token.value

            else :
                ln = -1
                if "token" in locals() :
                    ln = token.lineno
                self._eh.fatalError( line = ln, msg = "EOF in delimited value" )
                stop = True

        except sas.SasException, e :
            self._eh.fatalError( line = e._line, msg = "Lexer error: " + str( e._msg ) )
            stop = True

        return (val, stop)

    # top-level parse does not return anything
    #
    def _parse_file( self ) :
        """Top (file) level parse"""
        assert isinstance( self._lexer, sas.StarLexer )
        assert isinstance( self._ch, sas.ContentHandler )
        assert isinstance( self._eh, sas.ErrorHandler )

        if self._verbose : sys.stdout.write( self.__class__.__name__ + "._parse_file()\n" )

        try :
            for token in self._lexer :

                if token.type in ("NL", "SPACE" ) : continue

                if token.type == "COMMENT" :
                    if self._ch.comment( line = token.lineno, text = token.value ) :
                        return
                    continue

                if token.type == "DATASTART" :
                    if self._ch.startData( line = token.lineno, name = token.value ) :
                        return
                    self._data_name = token.value
                    if self._parse_data() :
                        return
                    continue

                if self._eh.error( line = token.lineno, msg = "invalid token at file level: %s : %s" \
                        % (token.type, token.value,) ) :
                    return
            else :
                ln = -1
                if "token" in locals() :
                    ln = token.lineno
                self._ch.endData( line = ln, name = self._data_name )


        except sas.SasException, e :
            self._eh.fatalError( line = e._line, msg = "Lexer error: " + str( e._msg ) )
            return

    # returns a stop sign: if true: stop parsing
    #
    def _parse_data( self ) :
        """Parse data block"""
        assert isinstance( self._lexer, sas.StarLexer )
        assert isinstance( self._ch, sas.ContentHandler )
        assert isinstance( self._eh, sas.ErrorHandler )

        if self._verbose : sys.stdout.write( self.__class__.__name__ + "._parse_data()\n" )

        need_value = False
        last_tag = None

        try :
            for token in self._lexer :

                if token.type in ("NL", "SPACE" ) : continue

                if token.type == "COMMENT" :
                    if self._ch.comment( line = token.lineno, text = token.value ) :
                        return True
                    continue

                if token.type == "DATASTART" :
                    if need_value :
                        if self._eh.error( line = token.lineno, msg = "found data_%s, expected value" \
                                % (token.value,) ) :
                            return True

                    if self._ch.endData( line = token.lineno, name = self._data_name ) :
                        return True
                    self._data_name = "__FILE__"

                    if token.lexer.lexpos >= (len( token.value ) + 5):
                        token.lexer.lexpos -= (len( token.value ) + 5)
                    else :
                        raise sas.SasException( line = token.lineno, msg = "can't push back 'data_%s'!" \
                            % (token.value,) )
                    return False

                if token.type == "SAVESTART" :
                    if need_value :
                        if self._eh.error( line = token.lineno, msg = "found save_%s, expected value" \
                                % (token.value,) ) :
                            return True

                    if self._ch.startSaveframe( line = token.lineno, name = token.value ) :
                        return True

                    self._save_name = token.value
                    if self._parse_save() :
                        return True
                    continue

                if token.type == "LOOPSTART" :
                    if need_value :
                        if self._eh.error( line = token.lineno, msg = "found loop_, expected value" ) :
                                return True
                    if self._ch.startLoop( line = token.lineno ) :
                        return True
                    if self._parse_loop() :
                        return True
                    continue

                if token.type == "TAGNAME" :
                    if need_value :
                        if self._eh.error( line = token.lineno, msg = "found tag: %s, expected value" \
                                % (token.value,) ) :
                            return True
                    last_tag = (token.value,token.lineno)
                    need_value = True
                    continue

                if token.type in ("CHARACTERS","FRAMECODE") :
                    if not need_value :
                        if self._eh.error( line = token.lineno, msg = "value not expected here: %s" \
                                % (token.value,) ) :
                            return True
                    assert isinstance( last_tag, tuple )
                    if self._ch.data( tag = last_tag[0], tagline = last_tag[1], val = token.value,
                            valline = token.lineno, delim = sas.TOKENS[token.type], inloop = False ) :
                        return True
                    need_value = False
                    continue

                if token.type in ("SINGLESTART","TSINGLESTART","DOUBLESTART","TDOUBLESTART","SEMISTART") :
                    if not need_value :
                        if self._eh.error( line = token.lineno, msg = "value not expected here (found delimiter)" ) :
                            return True
                    assert isinstance( last_tag, tuple )
                    (val, stop) = self._read_value( token.type )
                    if stop : return True

                    if self._ch.data( tag = last_tag[0], tagline = last_tag[1], val = val,
                            valline = token.lineno, delim = sas.TOKENS[token.type], inloop = False ) :
                        return True
                    need_value = False
                    continue

                if self._eh.error( line = token.lineno, msg = "invalid token in data block: %s : %s" \
                        % (token.type, token.value,) ) :
                    return True

            else :
                ln = -1
                if "token" in locals() :
                    ln = token.lineno
                if need_value :
                    self._eh.fatalError( line = ln, msg = "premature EOF, expected value" )
                    return True
                self._ch.endData( line = ln, name = self._data_name )
                return True

        except sas.SasException, e :
            self._eh.fatalError( line = e._line, msg = "Lexer error: " + str( e._msg ) )
            return True

    # this is 99% a copy-paste of parse_data()
    # returns a stop sign: if true: stop parsing
    #
    def _parse_save( self ) :
        """Parse saveframe"""
        assert isinstance( self._lexer, sas.StarLexer )
        assert isinstance( self._ch, sas.ContentHandler )
        assert isinstance( self._eh, sas.ErrorHandler )

        if self._verbose : sys.stdout.write( self.__class__.__name__ + "._parse_save()\n" )

        need_value = False
        last_tag = None

        try :
            for token in self._lexer :

                if self._verbose : 
                    sys.stdout.write( self.__class__.__name__ + "._parse_save(): token\n" )
                    pprint.pprint( token )

                if token.type in ("NL", "SPACE" ) : continue

                if token.type == "COMMENT" :
                    if self._ch.comment( line = token.lineno, text = token.value ) :
                        return True
                    continue

                if token.type == "SAVEEND" :
                    if need_value :
                        if self._eh.error( line = token.lineno, msg = "found save_, expected value" ) :
                            return True

                    if self._ch.endSaveframe( line = token.lineno, name = self._save_name ) :
                        return True

                    self._save_name = "__UNNAMED__"
                    return False

                if token.type == "LOOPSTART" :
                    if need_value :
                        if self._eh.error( line = token.lineno, msg = "found loop_, expected value" ) :
                                return True
                    if self._ch.startLoop( line = token.lineno ) :
                        return True
                    if self._parse_loop() :
                        return True
                    continue

                if token.type == "TAGNAME" :
                    if need_value :
                        if self._eh.error( line = token.lineno, msg = "found tag: %s, expected value" \
                                % (token.value,) ) :
                            return True
                    last_tag = (token.value,token.lineno)
                    need_value = True
                    continue

                if token.type in ("CHARACTERS","FRAMECODE") :
                    if not need_value :
                        if self._eh.error( line = token.lineno, msg = "value not expected here: %s" \
                                % (token.value,) ) :
                            return True
                    assert isinstance( last_tag, tuple )
                    if self._ch.data( tag = last_tag[0], tagline = last_tag[1], val = token.value,
                            valline = token.lineno, delim = sas.TOKENS[token.type], inloop = False ) :
                        return True
                    need_value = False
                    continue

                if token.type in ("SINGLESTART","TSINGLESTART","DOUBLESTART","TDOUBLESTART","SEMISTART") :
                    if not need_value :
                        if self._eh.error( line = token.lineno, msg = "value not expected here (found delimiter)" ) :
                            return True
                    assert isinstance( last_tag, tuple )
                    (val, stop) = self._read_value( token.type )
                    if stop : return True

                    if self._ch.data( tag = last_tag[0], tagline = last_tag[1], val = val,
                            valline = token.lineno, delim = sas.TOKENS[token.type], inloop = False ) :
                        return True
                    need_value = False
                    continue

                if self._eh.error( line = token.lineno, msg = "invalid token in saveframe: %s : %s" \
                        % (token.type, token.value,) ) :
                    return True

            else :
                ln = -1
                if "token" in locals() :
                    ln = token.lineno
                if need_value :
                    self._eh.fatalError( line = ln, msg = "premature EOF, expected value" )
                    return True
                self._eh.fatalError( line = ln, msg = "premature EOF (no closing save_)" )
                return True

        except sas.SasException, e :
            self._eh.fatalError( line = e._line, msg = "Lexer error: " + str( e._msg ) )
            return True

    # returns a stop sign: if true: stop parsing
    #
    def _parse_loop( self ) :
        """Parse loop"""
        assert isinstance( self._lexer, sas.StarLexer )
        assert isinstance( self._ch, sas.ContentHandler )
        assert isinstance( self._eh, sas.ErrorHandler )

        if self._verbose : sys.stdout.write( self.__class__.__name__ + "._parse_loop()\n" )

        reading_tags = True
        reading_vals = False
        tags = []
        tag_idx = -1
        numvals = 0

        try :
            for token in self._lexer :

                if self._verbose : 
                    sys.stdout.write( self.__class__.__name__ + "._parse_loop(): token\n" )
                    pprint.pprint( token )

                if token.type in ("NL", "SPACE" ) : continue

                if token.type == "COMMENT" :
                    if self._ch.comment( line = token.lineno, text = token.value ) :
                        return True
                    continue

# exit points: the loop ends with another loop or a data block or a tag or or save_ or eof after values
# BMRB uses stop_
#
                if token.type == "STOP" :
                    if reading_tags :
                        if len( tags ) < 1 :
                            if self._eh.error( line = token.lineno, msg = "Loop with no tags" ) :
                                return True
                    if numvals < 1 :
                        if self._eh.error( line = token.lineno, msg = "Loop with no values" ) :
                            return True
                    if (numvals % len( tags )) != 0 :
                        if self._eh.error( line = token.lineno, msg = "Loop count error" ) :
                            return True
                    if self._ch.endLoop( line = token.lineno ) :
                        return True
                    return False

                if token.type in ("DATASTART","SAVESTART") :
                    if reading_tags :
                        if len( tags ) < 1 :
                            if self._eh.error( line = token.lineno, msg = "Loop with no tags" ) :
                                return True
                        if self._eh.error( line = token.lineno, msg = "found data_%s, expected value" \
                                % (token.value,) ) :
                            return True
                    else :
                        if (numvals % len( tags )) != 0 :
                            if self._eh.error( line = token.lineno, msg = "Loop count error" ) :
                                return True
                    if self._ch.endLoop( line = token.lineno ) :
                        return True
# ugh
#
                    if token.lexer.lexpos > (len( token.value ) + 4) :
                        token.lexer.lexpos -= (len( token.value ) + 5)
                    else :
                        raise sas.SasException( line = token.lineno, msg = "can't push back 'data/save_%s'!" \
                            % (token.value,) )
                    return False

                if token.type in ("SAVEEND", "LOOPSTART") :
#                    print "* got here"
                    if reading_tags :
                        if len( tags ) < 1 :
                            if self._eh.error( line = token.lineno, msg = "Loop with no tags" ) :
                                return True
                        if self._eh.error( line = token.lineno, msg = "found %s, expected value" \
                                % (token.value,) ) :
                            return True
                    else :
                        if (numvals % len( tags )) != 0 :
                            if self._eh.error( line = token.lineno, msg = "Loop count error" ) :
                                return True
                    if self._ch.endLoop( line = token.lineno ) :
                        return True

#                    print "** got here"
# push back "save_" or "loop_" to re-trigger in the caller 
#
#                    if token.type == "SAVEEND" :
#                        print "***", token.value
#                        print "***", len( token.value )
#                        token.lexer.lexpos -= len( str( token.value ) )
#                    elif token.type == "LOOPSTART" :
#
# "if" just in case
#
                    if token.lexer.lexpos > 4 :
                        token.lexer.lexpos -= len( str( token.value ) )
                    else :
                        raise sas.SasException( line = token.lineno, msg = "can't push back '%s'!" \
                            % (token.value,) )
                    return False

                if token.type == "TAGNAME" :
                    if reading_vals :
                        if (numvals % len( tags )) != 0 :
                            if self._eh.error( line = token.lineno, msg = "Loop count error" ) :
                                return True
                        if self._ch.endLoop( line = token.lineno ) :
                            return True
                        if token.lexer.lexpos >= len( token.value ) :
                            token.lexer.lexpos -= len( token.value )
                        else :
                            raise sas.SasException( line = token.lineno, msg = "can't push back '%s'!" \
                                % (token.value,) )

                        return False

# else collect tags
#
                    tags.append( (token.value,token.lineno) )
                    continue

                if token.type in ("CHARACTERS","FRAMECODE") :
                    if reading_tags :
                        reading_tags = False
                        reading_vals = True

                    if len( tags ) < 1 :
                        if self._eh.error( line = token.lineno, msg = "Loop with no tags" ) :
                            return True
                        else :
                            tags.append( "LOOP_WITH_NO_TAGS" )

                    numvals += 1
                    tag_idx += 1
                    if tag_idx >= len( tags ) :
                        tag_idx = 0

                    if self._ch.data( tag = tags[tag_idx][0], tagline = tags[tag_idx][1], val = token.value,
                            valline = token.lineno, delim = sas.TOKENS[token.type], inloop = True ) :
                        return True
                    continue

                if token.type in ("SINGLESTART","TSINGLESTART","DOUBLESTART","TDOUBLESTART","SEMISTART") :
                    if reading_tags :
                        reading_tags = False
                        reading_vals = True

                    if len( tags ) < 1 :
                        if self._eh.error( line = token.lineno, msg = "Loop with no tags" ) :
                            return True
                        else :
                            tags.append( "LOOP_WITH_NO_TAGS" )

                    numvals += 1
                    tag_idx += 1
                    if tag_idx >= len( tags ) :
                        tag_idx = 0

                    (val, stop) = self._read_value( token.type )
                    if stop : return True

                    if self._ch.data( tag = tags[tag_idx][0], tagline = tags[tag_idx][1], val = val,
                            valline = token.lineno, delim = sas.TOKENS[token.type], inloop = True ) :
                        return True
                    continue

                if self._eh.error( line = token.lineno, msg = "invalid token in loop: %s : %s" \
                        % (token.type, token.value,) ) :
                    return True

            else :
                ln = -1
                if "token" in locals() :
                    ln = token.lineno
                if len( tags ) < 1 :
                    if self._eh.error( line = ln, msg = "Loop with no tags" ) :
                        return True
                if numvals < 1 :
                    if self._eh.error( line = ln, msg = "Loop with no values" ) :
                        return True
                if (numvals % len( tags )) != 0 :
                    if self._eh.error( line = ln, msg = "Loop count error" ) :
                        return True
                if self._ch.endLoop( line = ln ) :
                    return True

# we may be in a saveframe
#
                if self._save_name != "__UNNAMED__" :
                    self._eh.fatalError(  line = ln, msg = "Premature EOF (no closing save_)" )
                    return True

# or not
#
                self._ch.endData( line = ln, name = self._data_name )
                return True

        except sas.SasException, e :
            self._eh.fatalError( line = e._line, msg = "Lexer error: " + str( e._msg ) )
            return True

###################################################################################################
# test handler
#
class Ch( sas.ContentHandler ) :
    def __init__( self, verbose = False ) :
        self._verbose = bool( verbose )
    def startData( self, line, name ) :
        if self._verbose : sys.stdout.write( "Start data block %s in line %d\n" % (name, line,) )
        return False
    def endData( self, line, name ) :
        if self._verbose : sys.stdout.write( "End data block %s in line %d\n" % (name, line,) )
    def startSaveframe( self, line, name ) :
        if self._verbose : sys.stdout.write( "Start saveframe %s in line %d\n" % (name, line,) )
        return False
    def endSaveframe( self, line, name ) :
        if self._verbose : sys.stdout.write( "End saveframe %s in line %d\n" % (name, line,) )
        return False
    def startLoop( self, line ) :
        if self._verbose : sys.stdout.write( "Start loop in line %d\n" % (line,) )
        return False
    def endLoop( self, line ) :
        if self._verbose : sys.stdout.write( "End loop in line %d\n" % (line,) )
    def comment( self, line, text ) :
        if self._verbose : sys.stdout.write( "Comment %s in line %d\n" % (text, line,) )
        return False
    def data( self, tag, tagline, val, valline, delim, inloop ) :
        if self._verbose :
            sys.stdout.write( "data item %s in line %d:%d, delim=%s, inloop=%s - " \
                % (tag, tagline, valline, str( delim ), str( inloop ),) )
            sys.stdout.write( val )
            sys.stdout.write( "\n" )
        return False

#
#
if __name__ == "__main__" :

    e = sas.ErrorHandler()
    c = Ch( verbose = False )
    l = sas.StarLexer( fp = sys.stdin, bufsize = 0, verbose = False )
    with sas.timer( "DDL" ) :
        p = Parser.parse( lexer = l, content_handler = c, error_handler = e, verbose = False )
