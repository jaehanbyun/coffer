// Licensed under the Apache License, Version 2.0.

export const REPOSITORY_NAME_PATTERN =
  /^[a-z0-9]+(?:[._-][a-z0-9]+)*(?:\/[a-z0-9]+(?:[._-][a-z0-9]+)*)*$/;
export const MAX_REPOSITORY_NAME_LENGTH = 255;

export const validateRepositoryName = (value) => {
  if (typeof value !== 'string') {
    return false;
  }
  return (
    value.length > 0 &&
    value.length <= MAX_REPOSITORY_NAME_LENGTH &&
    REPOSITORY_NAME_PATTERN.test(value)
  );
};
