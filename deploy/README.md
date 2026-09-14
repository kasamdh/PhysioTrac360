# Cheap test deployment (AWS Lightsail, SQLite, no domain)

For pre-production testing only, with synthetic data — not for real patient
data. See the repo README's "Production controls still required" section for
what's still missing before this could handle PHI.

Cost: ~$3.50-5/month (Lightsail's smallest Linux instance plan). No RDS, no
S3, no load balancer.

## 1. Create the instance

- Lightsail console -> Create instance -> Linux/Unix -> OS Only -> **Ubuntu
  24.04 LTS**
- Cheapest plan (512MB RAM / 1 vCPU / 20GB SSD)
- Attach the static IP Lightsail gives the instance (free while attached)
- Networking tab: allow HTTP (80) and SSH (22, already open by default)
- Default login user on this blueprint is `ubuntu`, home dir `/home/ubuntu`
  (that's what the paths in `deploy/*.service`/`deploy/nginx.conf` assume)

## 2. Install dependencies on the instance

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git nginx

git clone <your-repo-url> PhysioTrac360
cd PhysioTrac360
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Check `python3 --version` first — this needs 3.10 or newer (Ubuntu 24.04
ships 3.12, which is fine; 22.04 ships 3.10, also fine).

## 3. Build the frontend

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs
cd frontend && npm ci && npm run build && cd ..
```

## 4. Configure and initialize

```bash
cp deploy/env.production.example deploy/env.production
nano deploy/env.production   # fill in DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS
                               # (your Lightsail static IP), FRONTEND_BASE_URL

set -a; source deploy/env.production; set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py bootstrap_demo --password "<pick-a-password>"
```

## 5. Run Gunicorn as a service

```bash
sudo cp deploy/physiotrac360.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now physiotrac360
sudo systemctl status physiotrac360   # confirm it's active
```

## 6. Point Nginx at it

```bash
sudo cp deploy/nginx.conf /etc/nginx/conf.d/physiotrac360.conf
sudo nginx -t
sudo systemctl enable --now nginx
```

Visit `http://<your-static-ip>/login/`.

## Redeploying after a code change

```bash
cd PhysioTrac360
git pull
.venv/bin/pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
set -a; source deploy/env.production; set +a
.venv/bin/python manage.py migrate
.venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart physiotrac360
```

## Known gaps vs. production (see main README)

- SQLite, not RDS — fine for one instance with synthetic data, not for
  concurrent real usage
- HTTP only, no TLS — do not enter real credentials or PHI over this
- No S3/KMS, no Secrets Manager, no BAA — required before real patient data
