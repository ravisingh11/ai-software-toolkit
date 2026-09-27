import requests

# ok: proof.python-disabled-tls-verification
requests.get("https://example.test", verify=True)
