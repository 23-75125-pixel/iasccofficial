# Face Recognition Attendance System

A Flask, SQLite, and OpenCV-based attendance monitoring system. The app does not seed demo students or attendance records. A default admin account is saved to SQLite on first run, then you can register real users with camera-captured face samples.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install
npm run build:css
.venv/bin/flask --app app run --debug
```

Open `http://127.0.0.1:5000`.

The Tailwind CSS is compiled locally into `static/css/styles.css`, so the app does not rely on the Tailwind CDN in the browser.

## Project requirements covered

- Flask web interface and REST API
- Admin authentication
- Live browser camera feed
- OpenCV Haar Cascade face detection
- OpenCV LBPH face recognition model
- Automatic timestamped attendance logging
- Attendance dashboard, search, and CSV export
- Docker container configuration
- Kubernetes Deployment, Service, PVC, and 5 replicas

The default LBPH match threshold is `88`. You can tune it with:

```bash
FACE_MATCH_THRESHOLD=92 .venv/bin/flask --app app run --debug
```

After changing recognition settings, rebuild the saved model:

```bash
.venv/bin/flask --app app retrain-model
```

## Default admin

On a fresh database, the app creates this admin account in `instance/attendance.sqlite3`:

```text
Email: admin@example.com
Password: Admin@12345
```

You can override it before first run:

```bash
DEFAULT_ADMIN_EMAIL=admin@school.test DEFAULT_ADMIN_PASSWORD='ChangeMe123!' SECRET_KEY='replace-with-a-long-random-secret' .venv/bin/flask --app app run --debug
```

Set `DEFAULT_ADMIN_ENABLED=0` if you want to use the `/setup` page instead.

To add another admin from the terminal:

```bash
.venv/bin/flask --app app create-admin --email newadmin@example.com
```

The command will securely prompt for the password and save a hashed password in SQLite.

## Docker

```bash
docker build -t face-attendance-system:latest .
docker run --rm -p 5000:5000 -v "$PWD/instance:/app/instance" face-attendance-system:latest
```

To push the production image to GitHub Container Registry:

```bash
read -rsp "GitHub token with write:packages permission: " GHCR_TOKEN
echo
export GHCR_TOKEN
export IMAGE=ghcr.io/23-75125-pixel/iasccofficial:latest
echo "$GHCR_TOKEN" | docker login ghcr.io -u superjp --password-stdin
docker build -t "$IMAGE" .
docker push "$IMAGE"
```

## Kubernetes

Use this production manifest only after the GHCR image has been pushed successfully. For Minikube on this machine, skip this section and use the Minikube commands below.

The production manifest uses this image:

```text
ghcr.io/23-75125-pixel/iasccofficial:latest
```

The real Kubernetes secret values are in `k8s/attendance-system-secret.yaml`. That file is ignored by git; use `k8s/attendance-system-secret.example.yaml` as the safe template.

Deploy both the secret and app manifests:

```bash
kubectl apply -f k8s/attendance-system-secret.yaml -f k8s/attendance-system.yaml
kubectl rollout status deployment/face-attendance-web -n face-attendance
kubectl get pods -n face-attendance
kubectl get svc -n face-attendance
```

The deployment uses `replicas: 5`, a NodePort service on `30080`, and a PVC mounted at `/app/instance` for the SQLite database, face samples, snapshots, and trained model files. For multi-node clusters, use a storage class that supports `ReadWriteMany`.
If your GHCR package is private, create an image pull secret and add `imagePullSecrets` to the deployment:

```bash
kubectl create secret docker-registry ghcr-login \
  --namespace face-attendance \
  --docker-server=ghcr.io \
  --docker-username=superjp \
  --docker-password="$GHCR_TOKEN"

kubectl patch deployment face-attendance-web \
  --namespace face-attendance \
  --type merge \
  --patch '{"spec":{"template":{"spec":{"imagePullSecrets":[{"name":"ghcr-login"}]}}}}'
```

## Expose with ngrok

Keep Kubernetes running, then forward the service to localhost in one terminal:

```bash
kubectl port-forward -n face-attendance svc/face-attendance-service 5000:80
```

In another terminal, expose that forwarded port with ngrok:

```bash
ngrok http 5000
```

Open the HTTPS forwarding URL shown by ngrok. The HTTPS URL is best for browser camera access.

### Minikube

Use the Minikube manifest for local testing. It uses one replica, a `ReadWriteOnce` PVC, and the local Docker image, so you do not need to push to a registry.

```bash
minikube start
docker build -t face-attendance-system:latest .
minikube image load face-attendance-system:latest
kubectl apply -f k8s/attendance-system-minikube.yaml
kubectl rollout status deployment/face-attendance-web -n face-attendance
```

For browser camera access, open the app through localhost:

```bash
kubectl port-forward -n face-attendance svc/face-attendance-service 5000:80
```

Then visit `http://localhost:5000`.

To remove the Minikube deployment:

```bash
kubectl delete -f k8s/attendance-system-minikube.yaml
```

## Workflow

1. Log in with the default admin account.
2. Register a student and capture at least 3 face samples.
3. Start Live Attendance and let the browser camera scan one face at a time.
4. Review and export records from the Records page.

## Data

Runtime data is stored in `instance/`:

- `attendance.sqlite3`: admins, students, face samples, and attendance logs
- `faces/students/`: normalized face samples
- `faces/attendance/`: attendance snapshots
- `models/`: trained OpenCV LBPH recognition model
- `secret_key`: persistent Flask session secret

`instance/` is ignored by git so real student data stays local.
