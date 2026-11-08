"""One-time helper: authorise the app to send mail as your Gmail account.

Run it on your laptop, sign in as the account that should send the ledger
(e.g. bailscricketground@gmail.com), and it prints a refresh token. Paste that
token, with the client id and secret, into Render's Environment as
GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN.

    python gmail_auth.py

It asks only for the "send email" permission (gmail.send) -- it cannot read
your inbox. Nothing is written to disk; the token is printed once.
"""
import getpass
import http.server
import json
import os
import secrets
import socketserver
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/gmail.send"


def main():
    client_id = os.environ.get("GMAIL_CLIENT_ID") or input("OAuth client ID: ").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET") or getpass.getpass("OAuth client secret: ").strip()
    state = secrets.token_urlsafe(16)
    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if query.get("state", [""])[0] == state:
                result["code"] = query.get("code", [""])[0]
                result["error"] = query.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<p>Done. You can close this tab and return to the terminal.</p>")

        def log_message(self, *args):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        redirect_uri = f"http://127.0.0.1:{server.server_address[1]}"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
        })
        print("\nOpening your browser to sign in. If it does not open, visit:\n\n" + url + "\n")
        webbrowser.open(url)
        while "code" not in result:
            server.handle_request()

    if result.get("error") or not result.get("code"):
        raise SystemExit(f"Authorisation failed: {result.get('error') or 'no code returned'}")

    body = urllib.parse.urlencode({
        "code": result["code"], "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", data=body, timeout=20) as response:
        tokens = json.loads(response.read().decode())
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise SystemExit("Google returned no refresh token. Remove the app's access at "
                         "https://myaccount.google.com/permissions and run this again.")
    print("Success. Set these three in Render > Environment (never commit them):\n")
    print(f"  GMAIL_CLIENT_ID={client_id}")
    print("  GMAIL_CLIENT_SECRET=<the secret you just entered>")
    print(f"  GMAIL_REFRESH_TOKEN={refresh}\n")


if __name__ == "__main__":
    main()
