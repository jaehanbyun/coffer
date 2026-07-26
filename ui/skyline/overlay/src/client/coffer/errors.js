// Licensed under the Apache License, Version 2.0.

const FAILURE_MESSAGES = {
  401: 'Registry authentication is required.',
  403: 'Registry access is not permitted.',
  404: 'The registry resource was not found.',
  409: 'The registry resource already exists.',
  503: 'The registry service is unavailable.',
};

export default class CofferRequestError extends Error {
  constructor(status) {
    const safeStatus = Number.isInteger(status) ? status : 0;
    super(FAILURE_MESSAGES[safeStatus] || 'The registry request failed.');
    this.name = 'CofferRequestError';
    this.response = {
      status: safeStatus,
      data: '',
    };
  }
}
