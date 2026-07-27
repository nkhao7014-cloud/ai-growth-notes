from getpass import getpass
from pwdlib import PasswordHash

password = getpass("Password (12+ characters): ")
confirmation = getpass("Confirm password: ")
if password != confirmation:
    raise SystemExit("Passwords do not match")
if len(password) < 12:
    raise SystemExit("Password must contain at least 12 characters")
print(PasswordHash.recommended().hash(password))
