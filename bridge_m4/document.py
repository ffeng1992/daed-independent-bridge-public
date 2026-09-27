"""Lossless typed lexical tree for DAE section/rule documents.

Nested delimiters, token kinds and all trivia are explicit IR; no direct
GraphQL string interpolation. Semantic acceptance still requires official DAE.
"""
from dataclasses import dataclass,asdict
import re
from .extensions import need

@dataclass(frozen=True)
class Token:
    kind: str
    text: str

@dataclass(frozen=True)
class Document:
    section: str
    tokens: tuple
    def render(self):return ''.join(t.text for t in self.tokens)
    def json(self):return {'section':self.section,'tokens':[asdict(t) for t in self.tokens]}

def parse(text, section):
    need(type(text) is str and '\x00' not in text and len(text)<4*1024*1024,'INVALID_DOCUMENT',section)
    tokens=[];stack=[];i=0
    while i<len(text):
        start=i;c=text[i]
        if c.isspace():
            while i<len(text) and text[i].isspace():i+=1
            kind='whitespace'
        elif c=='#':
            while i<len(text) and text[i]!='\n':i+=1
            kind='comment'
        elif c in ('"',"'",'`'):
            quote=c;i+=1;closed=False
            while i<len(text):
                if text[i]=='\\':i+=2;continue
                if text[i]==quote:i+=1;closed=True;break
                i+=1
            need(closed,'INVALID_DOCUMENT_STRING',section);kind='string'
        elif c in '{}()':
            if c in '{(':stack.append(c)
            else:
                need(bool(stack) and stack.pop()==('{' if c=='}' else '('),'INVALID_DOCUMENT_NESTING',section)
            i+=1;kind='delimiter'
        elif c in ':,':i+=1;kind='separator'
        else:
            while i<len(text) and not text[i].isspace() and text[i] not in '{}():,#\"\'`':i+=1
            kind='atom'
        tokens.append(Token(kind,text[start:i]))
    need(not stack,'INVALID_DOCUMENT_NESTING',section)
    meaningful=[t for t in tokens if t.kind not in ('whitespace','comment')]
    need(len(meaningful)>=3 and meaningful[0].text==section and meaningful[1].text=='{' and meaningful[-1].text=='}','INVALID_DOCUMENT_SECTION',section)
    # A second section after the initial closing brace is forbidden.
    depth=0
    for n,t in enumerate(meaningful[1:],1):
        if t.text=='{':depth+=1
        elif t.text=='}':
            depth-=1
            need(depth>0 or n==len(meaningful)-1,'EXTRA_DOCUMENT_SECTION',section)
    return Document(section,tuple(tokens))
