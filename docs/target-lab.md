# Docker Target Lab — Ground Truth Specification

**Status:** Active · **Module:** ASM Test Fixture (W1-10)  
**Author:** Islam Abdelslam · **Reviewer:** Zyad Mohamed  

---

## 1. Overview and Purpose

The **Docker Target Lab** is a local, deterministic scanning test fixture designed to validate the **Attack Surface Management (ASM)** scanner modules built in Week 4.

Unlike live internet hosts which may change, rate limit, or go offline unexpectedly, the Target Lab provides **immutable, known-good ground truth** across four varied service archetypes.

### Target Summary Matrix

| Service Name | Host Port | Container Port | Protocol | Server Banner | Technologies / Distinguishing Features | Expected SANs |
|---|---|---|---|---|---|---|
| **`lab-nginx`** | `8081` | `80` | HTTP | `nginx/1.25.4` | Nginx web server, `X-Powered-By: PHP/8.2.10`, `X-Lab-Target: nginx-standard` | N/A |
| **`lab-apache`** | `8082` | `80` | HTTP | `Apache/2.4.52 (Unix)` | Apache HTTPD 2.4, legacy signature, `X-Lab-Target: apache-legacy` | N/A |
| **`lab-nonstandard`** | `8888` | `8888` | HTTP | `nginx/1.25.4` | Non-standard port listening, `X-Service-Type: Custom-Port-Tester`, `X-Lab-Target: nonstandard-port-8888` | N/A |
| **`lab-tls-san`** | `8443` | `443` | HTTPS | `nginx/1.25.4` | Self-signed X.509 v3 TLS certificate, TLSv1.2 & TLSv1.3, `X-Lab-Target: tls-san-multi-domain` | `target4.lab.local`<br/>`sub1.target4.lab.local`<br/>`api.target4.lab.local`<br/>`admin.internal.tem.local`<br/>`127.0.0.1` |

---

## 2. Managing the Lab

The Target Lab is isolated under the Docker Compose `lab` profile so that standard application development (`just up`) does not launch scan fixtures unnecessarily.

```bash
# Start all 4 target lab services in detached mode
just lab-up

# Follow logs from target lab containers
just lab-logs

# Stop and remove target lab containers
just lab-down
```

---

## 3. Target Specifications & Expected Scanner Findings

### Target 1: `lab-nginx` (Standard Nginx Web Server)
- **Host Address:** `http://localhost:8081`
- **Transport / Port:** TCP / `8081`
- **Application Protocol:** HTTP/1.1
- **Expected Scanner Discoveries:**
  - **Open Port:** `8081/tcp`
  - **Service Name:** `http`
  - **Server Header:** `Server: nginx/1.25.4`
  - **Technology Fingerprints:**
    - Web Server: `Nginx 1.25.4`
    - Injected Header: `X-Powered-By: PHP/8.2.10`
    - Custom Tag: `X-Lab-Target: nginx-standard`
  - **HTTP Response Code:** `200 OK`
  - **HTML Page Title:** `TEM Target Lab - Nginx Web Server`
- **Verification Command:**
  ```bash
  curl -I http://localhost:8081
  ```

---

### Target 2: `lab-apache` (Legacy Apache Web Server)
- **Host Address:** `http://localhost:8082`
- **Transport / Port:** TCP / `8082`
- **Application Protocol:** HTTP/1.1
- **Expected Scanner Discoveries:**
  - **Open Port:** `8082/tcp`
  - **Service Name:** `http`
  - **Server Header:** `Server: Apache/2.4.52 (Unix)`
  - **Technology Fingerprints:**
    - Web Server: `Apache HTTP Server 2.4.52`
    - Custom Tag: `X-Lab-Target: apache-legacy`
  - **HTTP Response Code:** `200 OK`
  - **HTML Page Title:** `TEM Target Lab - Apache Legacy Server`
- **Verification Command:**
  ```bash
  curl -I http://localhost:8082
  ```

---

### Target 3: `lab-nonstandard` (Non-Standard Port Service)
- **Host Address:** `http://localhost:8888`
- **Transport / Port:** TCP / `8888`
- **Application Protocol:** HTTP/1.1
- **Scanner Purpose:** Catches probers that assume HTTP runs only on ports 80/443 or make hardcoded port lists.
- **Expected Scanner Discoveries:**
  - **Open Port:** `8888/tcp`
  - **Service Name:** `http`
  - **Server Header:** `Server: nginx/1.25.4`
  - **Technology Fingerprints:**
    - Web Server: `Nginx 1.25.4`
    - Injected Header: `X-Service-Type: Custom-Port-Tester`
    - Custom Tag: `X-Lab-Target: nonstandard-port-8888`
  - **HTTP Response Code:** `200 OK`
  - **HTML Page Title:** `TEM Target Lab - NonStandard Port 8888`
- **Verification Command:**
  ```bash
  curl -I http://localhost:8888
  ```

---

### Target 4: `lab-tls-san` (Multi-SAN TLS / HTTPS Server)
- **Host Address:** `https://localhost:8443`
- **Transport / Port:** TCP / `8443`
- **Application Protocol:** HTTPS (TLS 1.2 / TLS 1.3)
- **Scanner Purpose:** Validates SSL/TLS certificate fetching, certificate parsing, and extracting SANs for secondary subdomain discovery.
- **Expected Scanner Discoveries:**
  - **Open Port:** `8443/tcp`
  - **Service Name:** `https` / `ssl`
  - **TLS Protocols Supported:** `TLSv1.2`, `TLSv1.3`
  - **Certificate Type:** Self-Signed X.509 v3
  - **Subject Common Name (CN):** `target4.lab.local`
  - **Issuer:** `CN=target4.lab.local, O=TEM-Platform, OU=Target-Lab`
  - **Subject Alternative Names (SANs):**
    1. `target4.lab.local` (DNS)
    2. `sub1.target4.lab.local` (DNS)
    3. `api.target4.lab.local` (DNS)
    4. `admin.internal.tem.local` (DNS)
    5. `127.0.0.1` (IP)
  - **HTTP Response Code:** `200 OK`
  - **HTML Page Title:** `TEM Target Lab - Multi-SAN TLS Server`
- **Verification Command:**
  ```bash
  openssl s_client -connect localhost:8443 -showcerts </dev/null 2>/dev/null | openssl x509 -noout -text
  ```

---

## 4. Ground Truth Test Plan for ASM Modules (Week 4)

When implementing the ASM scanner in Week 4:

1. **Port Scanner Test:** Probe `localhost` across ports `8080-8890`.
   - **Must find open ports:** `8081`, `8082`, `8443`, `8888`.
   - **Must report all other ports in range as closed / filtered.**
2. **Banner Grabber Test:** Send raw TCP request to ports `8081` and `8082`.
   - Port 8081 must yield `nginx/1.25.4`.
   - Port 8082 must yield `Apache/2.4.52 (Unix)`.
3. **TLS SAN Discovery Test:** Query port `8443` certificate.
   - Must extract all 4 domain names (`target4.lab.local`, `sub1.target4.lab.local`, `api.target4.lab.local`, `admin.internal.tem.local`).
   - Secondary discovery loop must automatically enqueue extracted SAN domains for subsequent DNS resolution.
