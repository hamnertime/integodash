import datetime
import os
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

CERT_FILE = "cert.pem"
KEY_FILE = "key.pem"

def generate_self_signed_cert():
    """
    Generates a self-signed SSL certificate and a private key,
    saving them as cert.pem and key.pem.
    """
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        print(f"'{CERT_FILE}' and '{KEY_FILE}' already exist. Skipping generation.")
        return

    print("Generating a new self-signed SSL certificate...")

    # 1. Generate our private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 2. Define the certificate's subject and issuer
    # For a self-signed cert, the subject and issuer are the same.
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"Oregon"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"Roseburg"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Integotec Billing Dash"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])

    # 3. Build the certificate
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
        .not_valid_after(
            # Certificate will be valid for 1 year
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
        )
        .add_extension(
            # Basic constraints: identifies this as a CA cert (required for self-signed)
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        # Sign the certificate with our private key
        .sign(private_key, hashes.SHA256())
    )

    # 4. Write private key to key.pem
    print(f"Writing private key to '{KEY_FILE}'...")
    with open(KEY_FILE, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    # 5. Write certificate to cert.pem
    print(f"Writing certificate to '{CERT_FILE}'...")
    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print("\nCertificate and key generated successfully.")

if __name__ == "__main__":
    generate_self_signed_cert()
