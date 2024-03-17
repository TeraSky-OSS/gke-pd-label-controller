# GKE PD Label Controller

## Introduction

This project provides a Kubernetes controller that automatically adds labels to GCP (Google Cloud Platform) disks based on annotations defined on Kubernetes PersistentVolumeClaims (PVCs). It's designed to run within a Google Kubernetes Engine (GKE) cluster and uses the Python programming language for its implementation.

To add labels to GCP PDs, simply add the annotation `pd-label-controller.terasky.com/labels` with a comma-separated list of labels as its value (for example: `owner=daniel,project=test`) to your PVC configuration.

> **Note:** Once the relevant annotation is added to a PVC, the controller will take ownership of the related PD labels, and will override all labels (not starting with `goog-`) with the labels defined in the annotation value.

## Prerequisites

Before you begin, ensure you have the following:

- A Google Cloud Platform (GCP) project.
- A Google Kubernetes Engine (GKE) cluster.
- A container registry repository to host the Controller Docker image.
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
export GCP_PROJECT_ID="" # Set your GCP project iD

# Run the following commands to set additional environment variables
export GCP_SA_NAME="pd-label-controller"                                      # You can modify this according to your needs
export GCP_SA_EMAIL="$GCP_SA_NAME@${GCP_PROJECT_ID}.iam.gserviceaccount.com"  # DON'T change this
export GCP_CUSTOM_ROLE_NAME="gke_pd_label_controller"                         # You can modify this according to your needs
export CONTROLLER_NAMESPACE="pd-label-controller"                             # You can modify this according to your needs
export CONTROLLER_SA_NAME="pd-label-controller"                               # You can modify this according to your needs
```

> Explanation for the environment variables:
> - `GCP_PROJECT_ID` - The ID of the GCP project that your GKE cluster is running, and in which the Service Account will be created
> - `GCP_SA_NAME` - The name of the GCP Service Account that will be created and used to update the labels on the GCP PDs
> - `GCP_SA_EMAIL` - The full email of the GCP Service Account
> - `GCP_CUSTOM_ROLE_NAME` - The name of the custom IAM role that will be attached to the GCP Service Account
> - `CONTROLLER_NAMESPACE` - The GKE Kubernetes namespace in which you'll deploy the controller resources
> - `CONTROLLER_SA_NAME` - The name of the GKE Kubernetes Service Account that will be created in within the cluster (in the chosen namespace)

### Create GCP Service Account

```bash
# Create tbe service account
gcloud --project $GCP_PROJECT_ID iam service-accounts create $GCP_SA_NAME --display-name $GCP_SA_NAME

# Create a custom role
gcloud --project $GCP_PROJECT_ID iam roles create $GCP_CUSTOM_ROLE_NAME \
  --title "GKE PD Label Controller" \
  --description "Custom role for managing the labels of persistent disks by the GKE PD Label Controller" \
  --permissions "compute.disks.get,compute.disks.setLabels" \
  --stage "GA"

# Assign the custom role to the service account
gcloud --project $GCP_PROJECT_ID projects add-iam-policy-binding $GCP_PROJECT_ID \
  --member serviceAccount:$GCP_SA_EMAIL \
  --role "projects/$GCP_PROJECT_ID/roles/$GCP_CUSTOM_ROLE_NAME"
```

### Link GKE Service Account to GCP Service Account

Add an IAM policy binding between the workload identity GCP Service Account and PD Label Controller GCP Service Account. This will link the PD Label Controller Kubernetes Service Account to PD Label Controller Kubernetes GCP Service Account.

```bash
gcloud --project $GCP_PROJECT_ID iam service-accounts add-iam-policy-binding $GCP_SA_EMAIL \
  --member "serviceAccount:$GCP_PROJECT_ID.svc.id.goog[${CONTROLLER_NAMESPACE}/${CONTROLLER_SA_NAME}]" \
  --role "roles/iam.workloadIdentityUser"
```

### Deploy GKE PD Label Controller

```bash
kubectl create namespace $CONTROLLER_NAMESPACE
cat install.yaml | envsubst | kubectl apply -f -
```

> **Note:** `envsubst` is being used to replace the placeholders in the YAML file with the relevant environment variables

You can validate that the controller is working by watching its logs:

```bash
kubectl -n $CONTROLLER_NAMESPACE logs -f -l app.kubernetes.io/name=pd-label-controller
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

## Remove the Controller

Run the following commands if you'd like to remove the controller from your environment

```bash
# Delete the controller from your GKE cluster
cat install.yaml | envsubst | kubectl delete -f -

# Delete the controller namespace from your GKE cluster
kubectl delete namespace $CONTROLLER_NAMESPACE

# Delete IAM policy bindings
gcloud --project $GCP_PROJECT_ID projects remove-iam-policy-binding $GCP_PROJECT_ID \
  --member serviceAccount:$GCP_SA_EMAIL \
  --role="projects/$GCP_PROJECT_ID/roles/$GCP_CUSTOM_ROLE_NAME"
gcloud --project $GCP_PROJECT_ID iam service-accounts remove-iam-policy-binding $GCP_SA_EMAIL \
  --role "roles/iam.workloadIdentityUser" \
  --member "serviceAccount:$GCP_PROJECT_ID.svc.id.goog[${CONTROLLER_NAMESPACE}/${CONTROLLER_SA_NAME}]"

# Delete the GCP role
gcloud --project $GCP_PROJECT_ID iam roles delete $GCP_CUSTOM_ROLE_NAME

# Delete the GCP Service Account
gcloud --project $GCP_PROJECT_ID iam service-accounts delete $GCP_SA_EMAIL
```

## Development

```bash
docker build -t gke-pd-label-controller .
docker tag gke-pd-label-controller danielvaknin/gke-pd-label-controller:v0.1.27 # Change the tag version
docker push danielvaknin/gke-pd-label-controller:v0.1.27 # Change the tag version
# Once pushed, also update the tag version in the `install.yaml` file before redeploying
```