# GKE PD Label Controller

## Introduction

This project provides a Kubernetes controller that automatically adds labels to GCP (Google Cloud Platform) disks based on annotations defined on Kubernetes PersistentVolumeClaims (PVCs). It's designed to run within a Google Kubernetes Engine (GKE) cluster and uses the Python programming language for its implementation.

To add labels to GCP PDs, simply add the annotation `pd-label-controller.terasky.com/labels` with a comma-separated list of labels (for example: `owner=daniel,project=test`) to your PVC configuration.

## Prerequisites

Before you begin, ensure you have the following:

- A Google Cloud Platform (GCP) project.
- A Google Kubernetes Engine (GKE) cluster.
- `kubectl` configured to communicate with your GKE cluster.
- Python 3.9+ and `pip` installed for local development and testing.

## Installation

To install and run the GKE PD Label Controller in your GKE cluster, follow these steps:

### Clone the Repository

```bash
git clone git@gitlab.com:skywiz-io/gke-pd-label-controller.git
cd gke-pd-label-controller
```

### Set Environment Variables

```bash
export GCP_PROJECT_ID="skywiz-sandbox" # Change this according to your GCP project ID
export GCP_SA_NAME="pd-label-controller"
export GCP_SA_EMAIL="$GCP_SA_NAME@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
export CONTROLLER_NAMESPACE="default"  # "pd-label-controller"
export CONTROLLER_SA_NAME="pd-label-controller"
```

### Create GCP Service Account

```bash
gcloud iam service-accounts create $GCP_SA_NAME --display-name $GCP_SA_NAME
gcloud projects add-iam-policy-binding $GCP_PROJECT_ID --member serviceAccount:$GCP_SA_EMAIL --role "roles/compute.storageAdmin"
```

### Link GKE Service Account to GCP Service Account

```bash
gcloud iam service-accounts add-iam-policy-binding $GCP_SA_EMAIL \
  --role "roles/iam.workloadIdentityUser" \
  --member "serviceAccount:$GCP_PROJECT_ID.svc.id.goog[${CONTROLLER_NAMESPACE:-"default"}/${CONTROLLER_SA_NAME}]"
```

### Deploy GKE PD Label Controller

```bash
cat install.yaml | envsubst | kubectl apply -f -
```

> **Note:** `envsubst` is being used to replace the placeholder in the YAML file with the relevant environment variable

You can validate that the controller is working by watching its logs:

```bash
kubectl logs -f -l app.kubernetes.io/name=pd-label-controller
```

## Usage

To use the GKE PD Label Controller, annotate your PVCs with the specified disk label information. The controller will automatically detect this annotation and update the corresponding GCP disks' labels.

Example PVC annotation:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: example-pvc
  annotations:
    pd-label-controller.terasky.com/labels: owner=daniel,project=test
spec:
  ...
```

## Test Functionality

You can test the controller by deploying some test resources.

```bash
kubectl apply -f example.yaml
```

Once you verified that everything works as expected, don't forget to delete all test resources

```bash
kubectl delete -f example.yaml
```

## Development

```bash
docker build -t gke-pd-label-controller .
docker tag gke-pd-label-controller danielvaknin/gke-pd-label-controller:v0.1.16 # Change the tag version
docker push danielvaknin/gke-pd-label-controller:v0.1.16 # Change the tag version
# Once pushed, also update the tag version in the `install.yaml` file before redeploying
```