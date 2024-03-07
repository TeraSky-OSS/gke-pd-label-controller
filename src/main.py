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
        initial=1.0,
        maximum=10.0,
        multiplier=2.0,
        deadline=60,
        max_attempts=5
    )

    @retry
    def retry_update_labels():
        existing_labels, fingerprint = fetch_disk_info(gcp_project, gcp_zone, gcp_disk_name)
        updated_labels = {**existing_labels, **new_labels}  # Merge labels
        attempt_label_update(gcp_project, gcp_zone, gcp_disk_name, updated_labels, fingerprint)

    try:
        retry_update_labels()
    except PreconditionFailed:
        logging.error("Failed to update disk labels due to a precondition failure even after retries.")
    except Exception as e:
        logging.error(f"Unexpected error when updating labels for disk '{gcp_disk_name}': {e}")

# def update_disk_labels(disk_id, labels):
#     gcp_project = disk_id.split('/')[1]
#     gcp_zone = disk_id.split('/')[3]
#     gcp_disk_name = disk_id.split('/')[5]

#     try:
#         # Get the current state of the disk to obtain the labels fingerprint
#         disk = compute_client.get(project=gcp_project, zone=gcp_zone, disk=gcp_disk_name)
#         fingerprint = disk.label_fingerprint
        
#         # Prepare the request with the new labels and the current fingerprint
#         disk_labels = compute_v1.Disk(labels=labels, label_fingerprint=fingerprint)
#         request = compute_v1.SetLabelsDiskRequest(
#             project=project,
#             zone=zone,
#             resource=disk_name,
#             global_set_labels_request_resource=compute_v1.GlobalSetLabelsRequest(
#                 label_fingerprint=fingerprint,
#                 labels=labels
#             ),
#         )
        
#         # Execute the request with retries
#         retry = Retry(predicate=lambda exc: isinstance(exc, PreconditionFailed), deadline=60)
#         retry(compute_client.set_labels)(request=request)
        
#         logging.info(f"Successfully updated labels for disk {disk_name}")
#     except PreconditionFailed:
#         logging.error("Failed to update disk labels due to a precondition failure. Labels fingerprint might be invalid or resource labels have changed.")
#     except Exception as e:
#         logging.error(f"Unexpected error when updating labels for disk {disk_name}: {e}")

#     # Get current disk labels
#     current_labels = None
#     label_fingerprint = None
#     try:
#         disk = compute_client.get(project=gcp_project, zone=gcp_zone, disk=gcp_disk_name)
#         current_labels = disk.labels
#         label_fingerprint = disk.label_fingerprint
#         logging.info(f"Current labels for disk '{gcp_disk_name}': {current_labels}")
#     except Exception as e:
#         logging.error(f"Error getting labels for disk '{gcp_disk_name}': {e}")

#     if current_labels != None and label_fingerprint != None:
#         # Convert new labels list to dictionary
#         new_labels = {}
#         for label in labels:
#             new_labels[label['key']] = label['value']
        
#         # Merge current and new labels
#         merged_labels = {**current_labels, **new_labels}
#         logging.info(f"All labels for disk '{gcp_disk_name}': {merged_labels}")

#         # Update the disk labels in GCP
#         try:
#             compute_client.set_labels(
#                 project=gcp_project, 
#                 zone=gcp_zone, 
#                 resource=gcp_disk_name, 
#                 zone_set_labels_request_resource={"labels": merged_labels, "label_fingerprint": label_fingerprint}
#             )
#             logging.info(f"Successfully updated PD labels for '{gcp_disk_name}'")
#         except Exception as e:
#             logging.error(f"Error updating PD labels for '{gcp_disk_name}': {e}")


logging.info(f'==============================================')
logging.info(f'GKE PD Label Controller (Developed by TeraSky)')
logging.info(f'==============================================')

# Watch for PV events
logging.info("Starting to watch for PV creation events")
w = watch.Watch()
for event in w.stream(v1.list_persistent_volume):
    if event['type'] == 'ADDED':
        pv = event['object']
        pv_name = pv.metadata.name
        logging.info(f"Caught a creation event of PV with name '{pv_name}'")

        pvc_annotations = None
        gcp_pd_id = None

        claim_ref = pv.spec.claim_ref
        if claim_ref:
            try:
                # Using the claim reference to fetch the PVC details
                pvc = v1.read_namespaced_persistent_volume_claim(name=claim_ref.name, namespace=claim_ref.namespace)
                logging.info(f"PV '{pv.metadata.name}' is bound to PVC '{pvc.metadata.name}' in namespace '{pvc.metadata.namespace}'")

                pvc_annotations = pvc.metadata.annotations
            except client.exceptions.ApiException as e:
                logging.error(f"Failed to get PVC '{claim_ref.name}' in namespace '{claim_ref.namespace}': {str(e)}")
        else:
            logging.info(f"PV '{pv.metadata.name}' is not bound to any PVC")
        
        if pv.spec.csi:
            gcp_pd_id = pv.spec.csi.volume_handle
            logging.info(f"Found GCP PD ID '{gcp_pd_id}' in PV '{pv_name}'")
        else:
            logging.info(f"PV '{pv_name}' is not backed by a GCP PD")

        if gcp_pd_id and pvc_annotations and RESERVED_PVC_ANNOTATION in pvc_annotations.keys():
            logging.info(f"Found annotation '{RESERVED_PVC_ANNOTATION}' on PVC '{claim_ref.name}'")
            pvc_labels_annotation_value = pvc_annotations[RESERVED_PVC_ANNOTATION]
            labels_string = pvc_labels_annotation_value.replace(' ', '')

            # Convert string of labels to list
            labels = []
            for label in labels_string.split(','):
                key, value = label.split('=')
                labels.append({'key': key, 'value': value})

            logging.info(f"Will apply the following labels to the PD: {labels}")
            update_disk_labels(gcp_pd_id, labels)
