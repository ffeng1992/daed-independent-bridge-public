"""Evidence sanitization: never publish raw CLI/network error output."""
import base64
import json
from pathlib import Path
import re


def redact(text):
    text = re.sub(r'(?i)bearer\s+\S+', 'Bearer [REDACTED]', text)
    text = re.sub(r'(?:ss|https?|udp|tcp)://[^\s\'"<>]+', '[REDACTED_URI]', text)
    text = re.sub(r'M1-SYNTHETIC-[A-Z0-9_-]+', '[REDACTED_SECRET]', text)
    secret = base64.urlsafe_b64encode(b'aes-128-gcm:M1-SYNTHETIC-PASSWORD-ONLY').decode().rstrip('=')
    text = text.replace(secret, '[REDACTED_CREDENTIAL]')
    # Include every fixture credential, including Unicode/escaped password variants.
    root = Path(__file__).resolve().parents[1]
    for path in (root/'fixtures/m1/success').glob('*.json'):
        value=json.loads(path.read_text())
        for page in value['nodePages']:
            for node in page['response']['data']['nodes']['edges']:
                encoded=node['link'].split('ss://',1)[1].split('@',1)[0]
                password=base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)).decode().split(':',1)[1]
                for secret in [encoded,password,json.dumps(password)[1:-1]]:
                    text=text.replace(secret,'[REDACTED_CREDENTIAL]')
    return text
