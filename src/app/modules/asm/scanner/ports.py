from __future__ import annotations

# Remote administration: the most valuable thing to find exposed.
_REMOTE_ACCESS = (21, 22, 23, 2222, 3389, 5900, 5901, 5985, 5986)

# Mail: SMTP/submission/IMAP/POP3 and their TLS variants.
_MAIL = (25, 110, 143, 465, 587, 993, 995)

# Name and directory services: DNS, Kerberos, LDAP(S), Global Catalog.
_NAME_DIRECTORY = (53, 88, 389, 636, 3268, 3269)

# HTTP(S) and the usual alternates for admin panels, dev servers, app servers.
_WEB = (
    80, 81, 443, 591, 3000, 4443, 5000, 7001, 8000, 8008, 8080, 8081, 8082,
    8088, 8090, 8181, 8443, 8444, 8880, 8888, 9000, 9080, 9090, 9443, 10000,
)  # fmt: skip

# File sharing and RPC: NFS, SMB, rsync, portmapper.
_FILE_RPC = (111, 135, 139, 445, 873, 2049)

# Databases and caches that should never face the internet.
_DATABASES = (
    1433, 1521, 3306, 5432, 5984, 6379, 9042, 9200, 9300, 11211, 27017, 27018,
    50000,
)  # fmt: skip

# Messaging, orchestration, and observability endpoints (Docker/K8s/etcd/etc.).
_MESSAGING_INFRA = (
    1883, 2181, 2375, 2376, 2379, 4369, 5601, 5672, 6443, 8161, 8200, 8500,
    8883, 9092, 9093, 9100, 10250, 15672, 61616,
)  # fmt: skip

# Proxies, VoIP, and other frequently exposed leftovers.
_MISC = (
    1080, 1723, 3128, 4848, 5060, 5061, 5555, 6000, 7077, 8009, 8118, 8983,
    9001, 9418, 50070,
)  # fmt: skip

CURATED_TCP_PORTS: tuple[int, ...] = tuple(
    sorted(
        {
            *_REMOTE_ACCESS,
            *_MAIL,
            *_NAME_DIRECTORY,
            *_WEB,
            *_FILE_RPC,
            *_DATABASES,
            *_MESSAGING_INFRA,
            *_MISC,
        }
    )
)