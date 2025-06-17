from signature_auth import create_signature

def test_signature():
    secret = "test_secret"
    payload = "param1=value1&param2=value2"
    signature = create_signature(secret, payload)
    print("Generated Signature:", signature)