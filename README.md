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

Docker and Kubernetes run with `TZ=Asia/Manila`, so attendance dates and times are recorded using Philippine time.

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

Use the Minikube manifest for local testing. It uses the local Docker image, so you do not need to push to a registry. The local manifest uses a `ReadWriteOnce` PVC and `replicas: 5`.

#### First setup

```bash
cd ~/aisccs

minikube start --memory=2200mb
docker build -t face-attendance-system:latest .
minikube image load face-attendance-system:latest
kubectl apply -f k8s/attendance-system-minikube.yaml
kubectl rollout status deployment/face-attendance-web -n face-attendance
kubectl port-forward -n face-attendance svc/face-attendance-service 5000:80
```

Then visit `http://localhost:5000`.

#### Normal start after `minikube stop`

Use this when you did not change code and you only want to run the system again.

```bash
cd ~/aisccs

minikube start --memory=2200mb
kubectl rollout status deployment/face-attendance-web -n face-attendance
kubectl port-forward -n face-attendance svc/face-attendance-service 5000:80
```

Then visit `http://localhost:5000`.

#### Run after code changes

Use this when you edited files and need the app inside Minikube to use the new code.

```bash
cd ~/aisccs

minikube start --memory=2200mb
docker build -t face-attendance-system:latest .
minikube image load face-attendance-system:latest
kubectl rollout restart deployment/face-attendance-web -n face-attendance
kubectl rollout status deployment/face-attendance-web -n face-attendance
kubectl port-forward -n face-attendance svc/face-attendance-service 5000:80
```

If the browser still shows old content, hard refresh with `Ctrl + Shift + R`.

#### Fresh reset records

Use this only when you want a clean dashboard and database. This deletes registered students, face samples, attendance logs, attendance snapshots, and the trained model. The default admin account will be recreated automatically.

```bash
cd ~/aisccs

minikube start --memory=2200mb

kubectl scale deployment/face-attendance-web --replicas=0 -n face-attendance
kubectl wait --for=delete pod -l app=face-attendance-web -n face-attendance --timeout=180s

minikube ssh -- "sudo find /tmp/hostpath-provisioner/face-attendance/face-attendance-instance -mindepth 1 -maxdepth 1 -exec rm -rf {} +"

kubectl scale deployment/face-attendance-web --replicas=5 -n face-attendance
kubectl rollout status deployment/face-attendance-web -n face-attendance

kubectl port-forward -n face-attendance svc/face-attendance-service 5000:80
```

#### Stop Minikube

Press `Ctrl+C` in the terminal running `kubectl port-forward`, then stop Minikube:

```bash
minikube stop
```

#### Remove the Minikube deployment

Use this when you want to remove the Kubernetes resources. This is different from the fresh reset command above.

```bash
cd ~/aisccs

kubectl delete -f k8s/attendance-system-minikube.yaml
```

#### Expose Minikube with ngrok

Run port-forward in one terminal:

```bash
kubectl port-forward -n face-attendance svc/face-attendance-service 5000:80
```

Run ngrok in another terminal:

```bash
ngrok http 5000
```

For a 5-replica demo, prefer exposing the Minikube NodePort directly instead of using `kubectl port-forward`:

```bash
ngrok http "$(minikube ip):30080"
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
