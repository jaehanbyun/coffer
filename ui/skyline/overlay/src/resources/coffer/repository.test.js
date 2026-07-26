import {
  MAX_REPOSITORY_NAME_LENGTH,
  validateRepositoryName,
} from './repository';

describe('Coffer repository validation', () => {
  it.each([
    'application',
    'team/application',
    'team-a/app_1.2',
    `a/${'b'.repeat(MAX_REPOSITORY_NAME_LENGTH - 2)}`,
  ])('accepts %s', (name) => {
    expect(validateRepositoryName(name)).toBe(true);
  });

  it.each([
    '',
    '/application',
    'team/',
    'Team/application',
    'team//application',
    'team/application:tag',
    `a/${'b'.repeat(MAX_REPOSITORY_NAME_LENGTH - 1)}`,
    null,
  ])('rejects %s', (name) => {
    expect(validateRepositoryName(name)).toBe(false);
  });
});
