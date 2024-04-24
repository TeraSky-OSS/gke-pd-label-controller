import logging
from google.cloud import compute_v1
from google.api_core.exceptions import PreconditionFailed
from google.api_core.retry import Retry
from kubernetes import client, config, watch
from kubernetes.config import ConfigException

# Configure logging
logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', level=logging.INFO)

RESERVED_PVC_ANNOTATION = 'pd-label-controller.terasky.com/labels'

try:
    # Try to load the in-cluster config, used when running inside a pod in the cluster
    config.load_incluster_config()
except ConfigException:
    # Fall back to kube-config file, used for local development
    config.load_kube_config()

# Initialize Kubernetes client
v1 = client.CoreV1Api()

# Initialize Google Compute client
compute_client = compute_v1.DisksClient()

def fetch_disk_info(project, zone, disk_name):
    # Fetch the current disk to get existing labels and label_fingerprint
    disk = compute_client.get(project=project, zone=zone, disk=disk_name)
    return disk.labels, disk.label_fingerprint

def attempt_label_update(project, zone, disk_name, labels, fingerprint):
    # Prepare the request with the merged labels and the current fingerprint
    request = compute_v1.SetLabelsDiskRequest(
        project=project,
        zone=zone,
        resource=disk_name,
        zone_set_labels_request_resource=compute_v1.ZoneSetLabelsRequest(
            label_fingerprint=fingerprint,
            labels=labels
        ),
    )
    
    # Execute the set_labels request
    compute_client.set_labels(request=request)
    logging.info(f"Successfully updated labels for disk '{disk_name}'.")

def update_disk_labels(disk_id, labels):
    gcp_project = disk_id.split('/')[1]
    gcp_zone = disk_id.split('/')[3]
    gcp_disk_name = disk_id.split('/')[5]

    # Convert new labels list to dictionary
    new_labels = {}
    for label in labels:
        new_labels[label['key']] = label['value']

    retry = Retry(
        predicate=lambda exc: isinstance(exc, PreconditionFailed),
        initial=5.0,
        maximum=10.0,
        multiplier=2.0,
        deadline=60,
        max_attempts=5
    )

    @retry
    def retry_update_labels():
        existing_labels, fingerprint = fetch_disk_info(gcp_project, gcp_zone, gcp_disk_name)

        # Filter labels to only labels created by Google
        google_managed_labels = {}
        for key, value in existing_labels.items():
            if key.startswith('goog-'):
                google_managed_labels[key] = value

        updated_labels = {**google_managed_labels, **new_labels}  # Merge labels

        if updated_labels != existing_labels:
            attempt_label_update(gcp_project, gcp_zone, gcp_disk_name, updated_labels, fingerprint)
        else:
            logging.info(f"Disk '{gcp_disk_name}' already contains all required labels.")

    try:
        retry_update_labels()
    except PreconditionFailed:
        logging.error("Failed to update disk labels due to a precondition failure even after retries.")
    except Exception as e:
        logging.error(f"Unexpected error when updating labels for disk '{gcp_disk_name}': {e}")


logging.info(f'==============================================')
logging.info(f'GKE PD Label Controller (Developed by TeraSky)')
logging.info(f'==============================================')

w = watch.Watch()
logging.info("Starting to watch for PVC creation/update events")
# Relevant docs: https://k8s-python.readthedocs.io/en/stable/genindex.html
for event in w.stream(v1.list_persistent_volume_claim_for_all_namespaces, timeout_seconds=0):
    if event['type'] in ['ADDED', 'MODIFIED']:
        pvc = event['object']

        # Relevant docs: https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1PersistentVolumeClaim.md
        pvc_annotations = pvc.metadata.annotations
        if pvc.status.phase == 'Bound' and RESERVED_PVC_ANNOTATION in pvc_annotations.keys():
            pvc_name = pvc.metadata.name
            pvc_namespace = pvc.metadata.namespace
            logging.info(f"Caught a creation/update event of a PVC with name '{pvc_name}' in namespace '{pvc_namespace}' that is bound to a PV and contains the annotation '{RESERVED_PVC_ANNOTATION}'")

            # Get bound PV
            pv_name = pvc.spec.volume_name
            logging.info(f"PVC '{pvc_name}' is bound to PV '{pv_name}'")
            pv = v1.read_persistent_volume(name=pv_name)

            gcp_pd_id = None
            if pv.spec.csi:
                gcp_pd_id = pv.spec.csi.volume_handle
            elif pv.spec.gce_persistent_disk:
                gcp_pd_id = pv.spec.gce_persistent_disk.pd_name
            else:
                logging.info(f"PV '{pv_name}' is not backed by a GCP PD")

            if gcp_pd_id:
                logging.info(f"Found GCP PD ID '{gcp_pd_id}' in PV '{pv_name}'")
                pvc_labels_annotation_value = pvc_annotations[RESERVED_PVC_ANNOTATION]
                labels_string = pvc_labels_annotation_value.replace(' ', '')

                # Convert string of labels to list
                labels = []
                for label in labels_string.split(','):
                    key, value = label.split('=')
                    labels.append({'key': key, 'value': value})

                logging.info(f"Will apply the following labels to the backed PD: {labels}")
                update_disk_labels(gcp_pd_id, labels)
                logging.info('------------------------------')