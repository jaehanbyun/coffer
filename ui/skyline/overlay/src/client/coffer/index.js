// Licensed under the Apache License, Version 2.0.

import Base from '../client/base';
import { cofferBase } from '../client/constants';
import CofferRequestError from './errors';

const UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DIGEST = /^sha256:[0-9a-f]{64}$/;
const TAG = /^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$/;
const TIMESTAMP =
  /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const ARTIFACT_KINDS = ['artifact', 'image', 'image_index'];
const ARTIFACT_KEYS = [
  'artifact_type',
  'digest',
  'kind',
  'media_type',
  'project_id',
  'pushed_at',
  'repository_id',
  'size_bytes',
  'tag_count',
  'tags',
  'tags_truncated',
  'updated_at',
];

const contractError = () => {
  throw new CofferRequestError(503);
};

const hasExactKeys = (value, keys) =>
  value &&
  typeof value === 'object' &&
  !Array.isArray(value) &&
  JSON.stringify(Object.keys(value).sort()) ===
    JSON.stringify([...keys].sort());

const validTimestamp = (value) =>
  typeof value === 'string' &&
  TIMESTAMP.test(value) &&
  Number.isFinite(Date.parse(value));

export const validateArtifact = (value, repositoryId) => {
  if (
    !hasExactKeys(value, ARTIFACT_KEYS) ||
    value.repository_id !== repositoryId ||
    typeof value.project_id !== 'string' ||
    !/^[A-Za-z0-9_-]{1,64}$/.test(value.project_id) ||
    typeof value.digest !== 'string' ||
    !DIGEST.test(value.digest) ||
    typeof value.media_type !== 'string' ||
    value.media_type.length < 1 ||
    value.media_type.length > 255 ||
    (value.artifact_type !== null &&
      (typeof value.artifact_type !== 'string' ||
        value.artifact_type.length < 1 ||
        value.artifact_type.length > 255)) ||
    !ARTIFACT_KINDS.includes(value.kind) ||
    !Number.isInteger(value.size_bytes) ||
    value.size_bytes < 0 ||
    value.size_bytes > 9223372036854776000 ||
    !validTimestamp(value.pushed_at) ||
    !validTimestamp(value.updated_at) ||
    !Array.isArray(value.tags) ||
    value.tags.length > 100 ||
    value.tags.some((tag) => typeof tag !== 'string' || !TAG.test(tag)) ||
    !Number.isSafeInteger(value.tag_count) ||
    value.tag_count < value.tags.length ||
    typeof value.tags_truncated !== 'boolean' ||
    value.tags_truncated !== value.tag_count > value.tags.length
  ) {
    contractError();
  }
  return value;
};

export const validateArtifactPage = (value, repositoryId, limit) => {
  if (
    !hasExactKeys(value, ['artifacts', 'next_marker']) ||
    !Array.isArray(value.artifacts) ||
    value.artifacts.length > limit
  ) {
    contractError();
  }
  value.artifacts.forEach((artifact) =>
    validateArtifact(artifact, repositoryId)
  );
  if (
    value.next_marker !== null &&
    (typeof value.next_marker !== 'string' ||
      !DIGEST.test(value.next_marker) ||
      value.artifacts.length === 0 ||
      value.artifacts[value.artifacts.length - 1].digest !== value.next_marker)
  ) {
    contractError();
  }
  return value;
};

const validateEndpointUrl = (value, path) => {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    contractError();
  }
  if (
    parsed.protocol !== 'https:' ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== path ||
    parsed.search ||
    parsed.hash
  ) {
    contractError();
  }
  return parsed;
};

export const validateEndpoint = (value) => {
  if (
    !hasExactKeys(value, ['version']) ||
    !hasExactKeys(value.version, [
      'endpoints',
      'id',
      'service_type',
      'status',
    ]) ||
    value.version.id !== 'v1' ||
    value.version.status !== 'CURRENT' ||
    value.version.service_type !== 'oci-registry' ||
    !hasExactKeys(value.version.endpoints, ['control', 'registry', 'token'])
  ) {
    contractError();
  }
  const { control, registry, token } = value.version.endpoints;
  const parsedControl = validateEndpointUrl(control, '/v1');
  const parsedRegistry = validateEndpointUrl(registry, '/v2/');
  const parsedToken = validateEndpointUrl(token, '/auth/token');
  if (
    parsedControl.origin !== parsedRegistry.origin ||
    parsedControl.origin !== parsedToken.origin
  ) {
    contractError();
  }
  return value;
};

const requireRepositoryId = (value) => {
  if (typeof value !== 'string' || !UUID.test(value)) {
    contractError();
  }
};

export class CofferClient extends Base {
  constructor() {
    super();
    this.repositories = {
      responseKey: 'repository',
      list: (params) => this.safe(this.request.get('repositories', params)),
      show: (id) => this.safe(this.request.get(`repositories/${id}`)),
      create: (data) => this.safe(this.request.post('repositories', data)),
    };
    this.artifacts = {
      list: (repositoryId, params = {}) => {
        requireRepositoryId(repositoryId);
        const limit = params.limit || 100;
        if (
          !Number.isInteger(limit) ||
          limit < 1 ||
          limit > 100 ||
          (params.marker !== undefined &&
            (typeof params.marker !== 'string' ||
              !DIGEST.test(params.marker))) ||
          (params.query !== undefined &&
            (typeof params.query !== 'string' ||
              params.query.length < 1 ||
              params.query.length > 128 ||
              params.query.trim() !== params.query))
        ) {
          contractError();
        }
        return this.safe(
          this.request.get(`repositories/${repositoryId}/artifacts`, params)
        ).then((value) => validateArtifactPage(value, repositoryId, limit));
      },
      show: (repositoryId, digest) => {
        requireRepositoryId(repositoryId);
        if (typeof digest !== 'string' || !DIGEST.test(digest)) {
          contractError();
        }
        return this.safe(
          this.request.get(`repositories/${repositoryId}/artifacts/${digest}`)
        ).then((value) => {
          if (!hasExactKeys(value, ['artifact'])) {
            contractError();
          }
          return {
            artifact: validateArtifact(value.artifact, repositoryId),
          };
        });
      },
    };
  }

  get baseUrl() {
    return cofferBase();
  }

  get resources() {
    return [];
  }

  safe = (request) =>
    request.catch((error) => {
      const status = error && error.response && error.response.status;
      throw new CofferRequestError(status);
    });

  endpoint = () =>
    this.safe(this.request.get()).then((value) => validateEndpoint(value));

  quota = () => this.safe(this.request.get('quota'));
}

const cofferClient = new CofferClient();
export default cofferClient;
