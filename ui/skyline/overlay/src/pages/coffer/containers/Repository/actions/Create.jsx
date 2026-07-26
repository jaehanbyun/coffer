// Licensed under the Apache License, Version 2.0.

import { inject, observer } from 'mobx-react';
import { ModalAction } from 'containers/Action';
import globalRootStore from 'stores/root';
import globalRepositoryStore from 'stores/coffer/repositories';
import {
  MAX_REPOSITORY_NAME_LENGTH,
  validateRepositoryName,
} from 'resources/coffer/repository';

export class CreateRepository extends ModalAction {
  static id = 'create-repository';

  static title = t('Create Repository');

  static allowed = () => {
    const roles = globalRootStore.roles || [];
    return Promise.resolve(
      roles.some((role) => ['admin', 'member'].includes(role.name))
    );
  };

  get name() {
    return t('Create Repository');
  }

  get defaultValue() {
    return {
      name: '',
      immutable_tags: false,
    };
  }

  get formItems() {
    return [
      {
        name: 'name',
        label: t('Repository Name'),
        type: 'input',
        required: true,
        maxLength: MAX_REPOSITORY_NAME_LENGTH,
        validator: (rule, value) =>
          validateRepositoryName(value)
            ? Promise.resolve()
            : Promise.reject(
                new Error(
                  t(
                    "Use lowercase path components and '.', '_' or '-' separators."
                  )
                )
              ),
      },
      {
        name: 'immutable_tags',
        label: t('Immutable Tags'),
        type: 'switch',
        tip: t('Prevent an existing tag from being overwritten.'),
      },
    ];
  }

  onSubmit = (values) => globalRepositoryStore.create(values);
}

export default inject('rootStore')(observer(CreateRepository));
