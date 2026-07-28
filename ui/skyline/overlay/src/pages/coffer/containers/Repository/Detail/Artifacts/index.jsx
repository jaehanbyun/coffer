// Licensed under the Apache License, Version 2.0.

import React from 'react';
import PropTypes from 'prop-types';
import { observer } from 'mobx-react';
import {
  Alert,
  Button,
  Empty,
  Input,
  Modal,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import { LeftOutlined, LinkOutlined, RightOutlined } from '@ant-design/icons';
import { formatSize } from 'utils';
import { getLocalTimeStr } from 'utils/time';
import { ArtifactStore } from 'stores/coffer/artifacts';
import {
  artifactReference,
  artifactType,
  connectionCommands,
  repositoryReference,
} from 'resources/coffer/artifact';
import styles from './index.less';

const { Paragraph, Text, Title } = Typography;
const { TabPane } = Tabs;

export class Artifacts extends React.Component {
  constructor(props) {
    super(props);
    this.store = new ArtifactStore();
    this.state = {
      appliedQuery: '',
      currentMarker: null,
      guideVisible: false,
      markerHistory: [],
      query: '',
      repositoryId: props.detail.id,
    };
  }

  static getDerivedStateFromProps(props, state) {
    if (props.detail.id === state.repositoryId) {
      return null;
    }
    return {
      appliedQuery: '',
      currentMarker: null,
      markerHistory: [],
      query: '',
      repositoryId: props.detail.id,
    };
  }

  componentDidMount() {
    this.loadArtifacts(null, '');
    this.store.fetchEndpoint().catch(() => {});
  }

  componentDidUpdate(previousProps) {
    if (previousProps.detail.id !== this.props.detail.id) {
      this.loadArtifacts(null, '');
      this.store.fetchEndpoint().catch(() => {});
    }
  }

  get baseReference() {
    return repositoryReference(this.store.endpoint, this.props.detail);
  }

  get columns() {
    const baseReference = this.baseReference;
    return [
      {
        title: t('Tags'),
        dataIndex: 'tags',
        width: 200,
        render: (tags, artifact) => (
          <div className={styles.tags}>
            {(tags || []).length ? (
              tags.map((tag) => <Tag key={tag}>{tag}</Tag>)
            ) : (
              <Text type="secondary">{t('Untagged')}</Text>
            )}
            {artifact.tags_truncated && (
              <Text type="secondary">
                {t('{count} tags total', { count: artifact.tag_count })}
              </Text>
            )}
          </div>
        ),
      },
      {
        title: t('Pushed'),
        dataIndex: 'pushed_at',
        width: 180,
        render: (value) => getLocalTimeStr(value),
      },
      {
        title: t('Type'),
        dataIndex: 'kind',
        width: 220,
        render: (value, artifact) => (
          <div>
            <Text strong>{artifactType(value)}</Text>
            <Text className={styles.mediaType} type="secondary">
              {artifact.artifact_type || artifact.media_type}
            </Text>
          </div>
        ),
      },
      {
        title: t('Size'),
        dataIndex: 'size_bytes',
        width: 120,
        render: (value) => formatSize(value),
      },
      {
        title: t('Digest'),
        dataIndex: 'digest',
        width: 290,
        render: (value) => (
          <Text copyable={{ text: value }} ellipsis={{ tooltip: value }}>
            {value}
          </Text>
        ),
      },
      {
        title: t('Pull Reference'),
        key: 'pull_reference',
        width: 340,
        render: (_, artifact) => {
          const value = artifactReference(baseReference, artifact);
          return value ? (
            <Text copyable={{ text: value }} ellipsis={{ tooltip: value }}>
              {value}
            </Text>
          ) : (
            '-'
          );
        },
      },
    ];
  }

  loadArtifacts = (marker, query) => {
    const params = { limit: 20 };
    if (marker) {
      params.marker = marker;
    }
    if (query) {
      params.query = query;
    }
    return this.store.fetch(this.props.detail.id, params).catch(() => {});
  };

  handleSearch = (value) => {
    const query = value.trim();
    this.setState(
      {
        appliedQuery: query,
        currentMarker: null,
        markerHistory: [],
        query,
      },
      () => this.loadArtifacts(null, query)
    );
  };

  handleNext = () => {
    const { nextMarker } = this.store;
    if (!nextMarker) {
      return;
    }
    const { appliedQuery, currentMarker, markerHistory } = this.state;
    this.setState(
      {
        currentMarker: nextMarker,
        markerHistory: [...markerHistory, currentMarker],
      },
      () => this.loadArtifacts(nextMarker, appliedQuery)
    );
  };

  handlePrevious = () => {
    const { appliedQuery, markerHistory } = this.state;
    if (!markerHistory.length) {
      return;
    }
    const previousMarker = markerHistory[markerHistory.length - 1];
    this.setState(
      {
        currentMarker: previousMarker,
        markerHistory: markerHistory.slice(0, -1),
      },
      () => this.loadArtifacts(previousMarker, appliedQuery)
    );
  };

  renderConnectionTab = (key, description, commands) => (
    <TabPane tab={key} key={key.toLowerCase()}>
      <Paragraph>{description}</Paragraph>
      <pre className={styles.commands}>{commands}</pre>
      <Text copyable={{ text: commands }}>{t('Copy commands')}</Text>
    </TabPane>
  );

  renderConnectionGuide() {
    const { guideVisible } = this.state;
    const baseReference = this.baseReference;
    if (!baseReference) {
      return null;
    }
    const commands = connectionCommands(baseReference);
    return (
      <Modal
        visible={guideVisible}
        title={t('Connect to {name}', { name: this.props.detail.name })}
        width={760}
        footer={[
          <Button
            key="close"
            onClick={() => this.setState({ guideVisible: false })}
          >
            {t('Close')}
          </Button>,
        ]}
        onCancel={() => this.setState({ guideVisible: false })}
      >
        <Alert
          type="info"
          showIcon
          message={t('Use a finite project-scoped application credential.')}
          description={t(
            'The secret is requested in a hidden prompt and is never displayed by Skyline Console.'
          )}
        />
        <Paragraph className={styles.prerequisites}>
          {t(
            'Install the OpenStackClient Coffer plugin and configure an operating-system credential store for your OCI client before logging in.'
          )}
        </Paragraph>
        <Tabs defaultActiveKey="docker">
          {this.renderConnectionTab(
            'Docker',
            t('Authenticate Docker, then tag and push an image.'),
            commands.docker
          )}
          {this.renderConnectionTab(
            'Podman',
            t('Authenticate Podman, then tag and push an image.'),
            commands.podman
          )}
          {this.renderConnectionTab(
            'Helm',
            t(
              'Authenticate Helm, then create and push a chart whose name maps to this repository.'
            ),
            commands.helm
          )}
          {this.renderConnectionTab(
            'ORAS',
            t('Authenticate ORAS, then push any OCI artifact.'),
            commands.oras
          )}
        </Tabs>
      </Modal>
    );
  }

  renderError() {
    if (!this.store.errorStatus) {
      return null;
    }
    const forbidden = this.store.errorStatus === 403;
    return (
      <Alert
        type={forbidden ? 'warning' : 'error'}
        showIcon
        message={
          forbidden
            ? t('You do not have permission to view artifacts.')
            : t('Artifact information is temporarily unavailable.')
        }
        action={
          forbidden ? null : (
            <Button
              size="small"
              onClick={() =>
                this.loadArtifacts(
                  this.state.currentMarker,
                  this.state.appliedQuery
                )
              }
            >
              {t('Retry')}
            </Button>
          )
        }
      />
    );
  }

  render() {
    const { items, isLoading, nextMarker } = this.store;
    const { appliedQuery, markerHistory, query } = this.state;
    const guideReady = Boolean(this.baseReference);
    return (
      <div className={styles.main}>
        <div className={styles.toolbar}>
          <div>
            <Title level={3}>{t('Images & Artifacts')}</Title>
            <Paragraph type="secondary">
              {t('Digest-addressed content admitted through this repository.')}
            </Paragraph>
          </div>
          <Space className={styles.actions}>
            <Input.Search
              allowClear
              aria-label={t('Search by tag or digest')}
              maxLength={128}
              placeholder={t('Search by tag or digest')}
              value={query}
              onChange={(event) => this.setState({ query: event.target.value })}
              onSearch={this.handleSearch}
            />
            <Button
              icon={<LinkOutlined />}
              loading={this.store.isEndpointLoading}
              disabled={!guideReady}
              onClick={() => this.setState({ guideVisible: true })}
            >
              {t('How to connect')}
            </Button>
          </Space>
        </div>

        {this.store.endpointErrorStatus !== 0 && (
          <Alert
            className={styles.endpointAlert}
            type="warning"
            showIcon
            message={t('Connection instructions are temporarily unavailable.')}
          />
        )}
        {this.renderError()}
        {!this.store.errorStatus && (
          <Table
            columns={this.columns}
            dataSource={items}
            loading={isLoading}
            locale={{
              emptyText: (
                <Empty
                  description={
                    appliedQuery
                      ? t('No images or artifacts match this search.')
                      : t('No images or artifacts yet.')
                  }
                />
              ),
            }}
            pagination={false}
            rowKey="digest"
            scroll={{ x: 1350 }}
          />
        )}
        {!this.store.errorStatus && (
          <div className={styles.pagination}>
            <Button
              icon={<LeftOutlined />}
              disabled={!markerHistory.length || isLoading}
              onClick={this.handlePrevious}
            >
              {t('Previous')}
            </Button>
            <Button
              disabled={!nextMarker || isLoading}
              onClick={this.handleNext}
            >
              {t('Next')} <RightOutlined />
            </Button>
          </div>
        )}
        {this.renderConnectionGuide()}
      </div>
    );
  }
}

Artifacts.propTypes = {
  detail: PropTypes.shape({
    id: PropTypes.string.isRequired,
    name: PropTypes.string.isRequired,
    project_id: PropTypes.string.isRequired,
  }).isRequired,
};

export default observer(Artifacts);
