// Licensed under the Apache License, Version 2.0.

import { action, observable } from 'mobx';
import client from 'client/coffer';

export class ArtifactStore {
  artifactRequest = 0;

  endpointRequest = 0;

  @observable
  items = [];

  @observable
  nextMarker = null;

  @observable
  endpoint = null;

  @observable
  isLoading = false;

  @observable
  isEndpointLoading = false;

  @observable
  errorStatus = 0;

  @observable
  endpointErrorStatus = 0;

  @action
  async fetch(repositoryId, params = {}) {
    this.artifactRequest += 1;
    const request = this.artifactRequest;
    this.isLoading = true;
    this.errorStatus = 0;
    try {
      const result = await client.artifacts.list(repositoryId, params);
      if (request === this.artifactRequest) {
        this.items = result.artifacts;
        this.nextMarker = result.next_marker;
      }
      return result;
    } catch (error) {
      if (request === this.artifactRequest) {
        this.items = [];
        this.nextMarker = null;
        this.errorStatus = error?.response?.status || 0;
      }
      throw error;
    } finally {
      if (request === this.artifactRequest) {
        this.isLoading = false;
      }
    }
  }

  @action
  async fetchEndpoint() {
    this.endpointRequest += 1;
    const request = this.endpointRequest;
    this.isEndpointLoading = true;
    this.endpointErrorStatus = 0;
    try {
      const result = await client.endpoint();
      if (request === this.endpointRequest) {
        this.endpoint = result.version.endpoints;
      }
      return this.endpoint;
    } catch (error) {
      if (request === this.endpointRequest) {
        this.endpoint = null;
        this.endpointErrorStatus = error?.response?.status || 0;
      }
      throw error;
    } finally {
      if (request === this.endpointRequest) {
        this.isEndpointLoading = false;
      }
    }
  }
}

export default new ArtifactStore();
