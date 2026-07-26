from django.conf import settings

settings.POLICY_FILES.update({"oci-registry": "coffer_policy.yaml"})
settings.DEFAULT_POLICY_FILES.update({"oci-registry": "coffer_policy.yaml"})
