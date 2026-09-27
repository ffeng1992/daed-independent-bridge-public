"""Secret-free failure locations: never format exception messages or local values."""
import json
import re
import traceback
from bridge_m2.security import Denied
from bridge_m1.common import Rejected

def failure(component,exc):
    code='REQUEST_FAILED'
    if isinstance(exc,Denied) and re.fullmatch('[A-Z][A-Z0-9_]{0,79}',str(exc)):code=str(exc)
    elif isinstance(exc,Rejected):code=exc.diagnostic['reasonCode']
    frames=[{'file':frame.filename,'line':frame.lineno,'function':frame.name} for frame in traceback.extract_tb(exc.__traceback__)]
    result={'component':component,'errorType':type(exc).__name__,'code':code,'frames':frames}
    if isinstance(exc,OSError):result['errno']=exc.errno
    print(json.dumps(result,sort_keys=True),flush=True)
    return result
