"""
MAIL — Sovereign Email/SMS Delivery
AnnulusLabs LLC · 2026

Direct SMTP delivery. No Gmail. No Twilio. No third party.
Connects directly to destination MX servers.
Tries ports 25, 587, 465 — handles Starlink/CGNAT port blocks.

For SMS: delivers to carrier email-to-SMS gateways.
For email: delivers directly to recipient's MX server.

Usage:
    from nox.mail import send_sms, send_email

    # SMS (direct to carrier gateway)
    send_sms("5551234567", "Build complete", carrier="tmobile")

    # Email
    send_email("user@example.com", "Subject", "Body text")

    # CLI
    python -m nox.mail sms "5551234567" "Hello"
    python -m nox.mail email "user@example.com" "Subject" "Body"
"""

import os
import sys
import json
import time
import socket
import smtplib
import logging
import struct
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional, List, Dict, Tuple

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════

OPERATOR_NUMBER = os.environ.get('OPENCLAW_OPERATOR_NUMBER', '')
OPERATOR_EMAIL = os.environ.get('OPENCLAW_OPERATOR_EMAIL', '')
NOX_FROM = os.environ.get('OPENCLAW_MAIL_FROM', 'openclaw@annuluslabs.com')
MAIL_LOG = Path(os.environ.get('OPENCLAW_MAIL_LOG', 'A:/AI/KERF/.kerf/mail_log.jsonl'))
MAIL_CONFIG = Path(os.environ.get('OPENCLAW_MAIL_CONFIG', 'A:/AI/KERF/.kerf/mail_config.json'))

CARRIER_GATEWAYS = {
    'tmobile':    '{number}@tmomail.net',
    'att':        '{number}@txt.att.net',
    'verizon':    '{number}@vtext.com',
    'sprint':     '{number}@messaging.sprintpcs.com',
    'uscellular': '{number}@email.uscc.net',
    'cricket':    '{number}@sms.cricketwireless.net',
    'mint':       '{number}@tmomail.net',
    'googlefi':   '{number}@msg.fi.google.com',
    'boost':      '{number}@sms.myboostmobile.com',
    'metro':      '{number}@mymetropcs.com',
    'visible':    '{number}@vzwpix.com',
}


# ═══════════════════════════════════════════════════
# MX RECORD LOOKUP (No external deps)
# ═══════════════════════════════════════════════════

def _dns_mx_query(domain: str) -> List[Tuple[int, str]]:
    """
    Look up MX records using raw DNS protocol.
    No dnspython needed. Just socket + UDP to system DNS.
    """
    # Build DNS query packet
    import random
    txn_id = random.randint(0, 65535)

    # Header: ID, flags(standard query), 1 question, 0 answers
    header = struct.pack('!HHHHHH', txn_id, 0x0100, 1, 0, 0, 0)

    # Question: domain name + type MX (15) + class IN (1)
    question = b''
    for label in domain.split('.'):
        question += bytes([len(label)]) + label.encode()
    question += b'\x00'  # root label
    question += struct.pack('!HH', 15, 1)  # type=MX, class=IN

    packet = header + question

    # Try system DNS resolvers
    dns_servers = []
    # Try to read resolv.conf or use common defaults
    try:
        # Windows: parse ipconfig /all for DNS servers
        import subprocess
        result = subprocess.run(['ipconfig', '/all'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            if 'DNS' in line and ':' in line:
                parts = line.split(':')[-1].strip()
                if parts and parts[0].isdigit():
                    dns_servers.append(parts)
    except Exception:
        pass

    # Fallback DNS servers
    if not dns_servers:
        dns_servers = ['8.8.8.8', '1.1.1.1', '9.9.9.9']

    for dns in dns_servers[:3]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(3)
            sock.sendto(packet, (dns, 53))
            response, _ = sock.recvfrom(4096)
            sock.close()

            # Parse response
            return _parse_mx_response(response)
        except Exception:
            continue

    return []


def _parse_mx_response(data: bytes) -> List[Tuple[int, str]]:
    """Parse DNS response for MX records."""
    if len(data) < 12:
        return []

    # Header
    _, flags, qdcount, ancount, _, _ = struct.unpack('!HHHHHH', data[:12])

    if flags & 0x8000 == 0:  # Not a response
        return []

    offset = 12

    # Skip questions
    for _ in range(qdcount):
        while offset < len(data):
            length = data[offset]
            if length == 0:
                offset += 1
                break
            if length & 0xC0 == 0xC0:  # Pointer
                offset += 2
                break
            offset += 1 + length
        offset += 4  # type + class

    # Parse answers
    mx_records = []
    for _ in range(ancount):
        if offset >= len(data):
            break

        # Skip name (might be pointer)
        if data[offset] & 0xC0 == 0xC0:
            offset += 2
        else:
            while offset < len(data) and data[offset] != 0:
                offset += 1 + data[offset]
            offset += 1

        if offset + 10 > len(data):
            break

        rtype, rclass, ttl, rdlength = struct.unpack('!HHIH', data[offset:offset+10])
        offset += 10

        if rtype == 15 and rdlength >= 4:  # MX record
            preference = struct.unpack('!H', data[offset:offset+2])[0]
            mx_name = _read_dns_name(data, offset + 2)
            mx_records.append((preference, mx_name))

        offset += rdlength

    mx_records.sort(key=lambda x: x[0])
    return mx_records


def _read_dns_name(data: bytes, offset: int) -> str:
    """Read a DNS name from response data (handles compression)."""
    labels = []
    seen = set()
    while offset < len(data):
        if offset in seen:
            break
        seen.add(offset)

        length = data[offset]
        if length == 0:
            break
        if length & 0xC0 == 0xC0:
            # Pointer
            ptr = struct.unpack('!H', data[offset:offset+2])[0] & 0x3FFF
            rest = _read_dns_name(data, ptr)
            if rest:
                labels.append(rest)
            break
        else:
            offset += 1
            labels.append(data[offset:offset+length].decode('ascii', errors='replace'))
            offset += length
    return '.'.join(labels)


# ═══════════════════════════════════════════════════
# DIRECT SMTP DELIVERY
# ═══════════════════════════════════════════════════

def _log_mail(to: str, subject: str, backend: str, success: bool, error: str = ''):
    """Log all mail attempts."""
    entry = {
        'timestamp': time.time(),
        'iso': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'to': to,
        'subject': subject,
        'backend': backend,
        'success': success,
        'error': error,
    }
    try:
        with open(MAIL_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception:
        pass


def _deliver_direct(to_addr: str, from_addr: str, msg: MIMEText) -> bool:
    """
    Deliver email directly to recipient's MX server.
    No relay. No third party. Just SMTP.
    Tries ports 25, 587, 465 to handle ISP port blocks (Starlink etc).
    """
    domain = to_addr.split('@')[-1]

    # Look up MX records
    mx_records = _dns_mx_query(domain)
    if not mx_records:
        # Fallback: try A record (domain itself)
        mx_records = [(0, domain)]

    helo = 'annuluslabs.com'

    for priority, mx_host in mx_records[:3]:
        # Try port 25 (standard), then 587 (submission/STARTTLS), then 465 (implicit TLS)
        for port in (25, 587, 465):
            try:
                if port == 465:
                    # Implicit TLS (SMTPS)
                    with smtplib.SMTP_SSL(mx_host, port, timeout=15) as server:
                        server.ehlo(helo)
                        server.sendmail(from_addr, [to_addr], msg.as_string())
                        log.info(f'Delivered via {mx_host}:{port} (SSL)')
                        return True
                else:
                    with smtplib.SMTP(mx_host, port, timeout=15) as server:
                        server.ehlo(helo)
                        try:
                            server.starttls()
                            server.ehlo(helo)
                        except Exception:
                            pass  # Not all servers support STARTTLS
                        server.sendmail(from_addr, [to_addr], msg.as_string())
                        log.info(f'Delivered via {mx_host}:{port}')
                        return True
            except Exception as e:
                log.debug(f'MX {mx_host}:{port} failed: {e}')
                continue

    return False


def _deliver_relay(to_addr: str, from_addr: str, msg: MIMEText, config: dict) -> bool:
    """Deliver via configured relay (Gmail, annuluslabs SMTP, etc.)."""
    smtp_host = config.get('smtp_host', '')
    smtp_port = config.get('smtp_port', 587)
    smtp_user = config.get('smtp_user', '')
    smtp_pass = config.get('smtp_pass', '')

    if not smtp_host or not smtp_user:
        return False

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception as e:
        log.warning(f'Relay {smtp_host} failed: {e}')
        return False


# ═══════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════

def send_sms(number: str, message: str, carrier: str = 'tmobile',
             urgent: bool = False) -> bool:
    """
    Send SMS via direct SMTP to carrier gateway.
    No API keys. No third party. Just DNS + SMTP.
    """
    gateway = CARRIER_GATEWAYS.get(carrier, CARRIER_GATEWAYS['tmobile'])
    to_addr = gateway.format(number=number)

    prefix = '[URGENT] ' if urgent else '[OC]'
    body = f'{prefix}{message}'[:160]

    msg = MIMEText(body)
    msg['From'] = NOX_FROM
    msg['To'] = to_addr
    msg['Subject'] = ''

    config = {}
    if MAIL_CONFIG.exists():
        try:
            config = json.loads(MAIL_CONFIG.read_text(encoding='utf-8'))
        except Exception:
            pass

    # Try direct delivery first (sovereign)
    if _deliver_direct(to_addr, NOX_FROM, msg):
        _log_mail(to_addr, 'SMS', 'direct', True)
        print(f'[MAIL] Direct to {carrier} gateway')
        return True

    # Try relay if configured
    if _deliver_relay(to_addr, NOX_FROM, msg, config):
        _log_mail(to_addr, 'SMS', 'relay', True)
        print(f'[MAIL] Via relay')
        return True

    # Log failure
    _log_mail(to_addr, 'SMS', 'failed', False, 'no delivery path')
    print(f'[MAIL FAILED] Logged to {MAIL_LOG}')
    print(f'  To: {number} ({carrier})')
    print(f'  Msg: {body}')
    return False


def send_email(to: str, subject: str, body: str,
               html: bool = False) -> bool:
    """
    Send email directly. Sovereign delivery.
    """
    if html:
        msg = MIMEMultipart('alternative')
        msg.attach(MIMEText(body, 'html'))
    else:
        msg = MIMEText(body)

    msg['From'] = NOX_FROM
    msg['To'] = to
    msg['Subject'] = subject
    msg['X-Mailer'] = 'OpenClaw Mail v1.0 (AnnulusLabs)'

    config = {}
    if MAIL_CONFIG.exists():
        try:
            config = json.loads(MAIL_CONFIG.read_text(encoding='utf-8'))
        except Exception:
            pass

    if _deliver_direct(to, NOX_FROM, msg):
        _log_mail(to, subject, 'direct', True)
        return True

    if _deliver_relay(to, NOX_FROM, msg, config):
        _log_mail(to, subject, 'relay', True)
        return True

    _log_mail(to, subject, 'failed', False, 'no delivery path')
    return False


def sms(message: str, urgent: bool = False) -> bool:
    """Shortcut: send SMS to the operator."""
    config = {}
    if MAIL_CONFIG.exists():
        try:
            config = json.loads(MAIL_CONFIG.read_text(encoding='utf-8'))
        except Exception:
            pass
    carrier = config.get('carrier', 'tmobile')
    return send_sms(OPERATOR_NUMBER, message, carrier=carrier, urgent=urgent)


def setup():
    """Interactive setup."""
    print('OpenClaw Sovereign Mail Setup')
    print('=' * 40)
    print()

    config = {}
    if MAIL_CONFIG.exists():
        try:
            config = json.loads(MAIL_CONFIG.read_text(encoding='utf-8'))
        except Exception:
            pass

    print("Carrier for SMS gateway:")
    for k in sorted(CARRIER_GATEWAYS.keys()):
        print(f'  {k}')
    config['carrier'] = input(f'\nCarrier [{config.get("carrier", "tmobile")}]: ').strip() or config.get('carrier', 'tmobile')

    print()
    print('Optional: SMTP relay (for when direct delivery is blocked)')
    print('  Leave blank for sovereign-only (direct MX delivery)')
    relay = input('SMTP relay host (e.g., smtp.gmail.com) [none]: ').strip()
    if relay:
        config['smtp_host'] = relay
        config['smtp_port'] = int(input('Port [587]: ').strip() or '587')
        config['smtp_user'] = input('Username/email: ').strip()
        config['smtp_pass'] = input('Password/app-password: ').strip()

    MAIL_CONFIG.write_text(json.dumps(config, indent=2), encoding='utf-8')
    print(f'\nSaved to {MAIL_CONFIG}')

    test = input('\nSend test SMS? [y/N]: ').strip().lower()
    if test == 'y':
        ok = sms('OpenClaw sovereign mail test - system operational')
        print('Delivered!' if ok else 'Failed (check carrier/network)')


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print('OpenClaw Sovereign Mail')
        print('  python -m nox.mail sms "message"')
        print('  python -m nox.mail email "to@addr" "subject" "body"')
        print('  python -m nox.mail --setup')
        print('  python -m nox.mail --test')
    elif args[0] == '--setup':
        setup()
    elif args[0] == '--test':
        sms('OpenClaw mail test')
    elif args[0] == 'sms' and len(args) >= 2:
        if len(args) == 2:
            sms(args[1])
        else:
            send_sms(args[1], ' '.join(args[2:]))
    elif args[0] == 'email' and len(args) >= 4:
        send_email(args[1], args[2], ' '.join(args[3:]))
    else:
        print(f'Unknown: {args}')
