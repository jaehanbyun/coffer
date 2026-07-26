// Licensed under the Apache License, Version 2.0.

import React from 'react';
import { Alert, Card, Col, Progress, Row, Skeleton } from 'antd';
import { observer } from 'mobx-react';
import { formatSize } from 'utils';
import globalQuotaStore from 'stores/coffer/quota';

export const quotaPercent = (quota) => {
  const { limit_bytes: limit = 0, used_bytes: used = 0 } = quota || {};
  if (limit <= 0) {
    return 0;
  }
  return Math.min(100, Math.round((used / limit) * 100));
};

export class QuotaSummary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      state: 'loading',
    };
  }

  componentDidMount() {
    this.load();
  }

  load = async () => {
    this.setState({ state: 'loading' });
    try {
      await globalQuotaStore.fetch();
      this.setState({ state: 'available' });
    } catch (error) {
      const status = error && error.response && error.response.status;
      this.setState({
        state: status === 404 ? 'notConfigured' : 'unavailable',
      });
    }
  };

  renderUnavailable() {
    const { state } = this.state;
    const message =
      state === 'notConfigured'
        ? t('Registry quota is not configured for this project.')
        : t('Registry quota is temporarily unavailable.');
    return <Alert type="warning" showIcon message={message} />;
  }

  render() {
    const { state } = this.state;
    if (state === 'loading') {
      return <Skeleton active paragraph={{ rows: 1 }} />;
    }
    if (state !== 'available') {
      return this.renderUnavailable();
    }
    const {
      limit_bytes: limit = 0,
      used_bytes: used = 0,
      reserved_bytes: reserved = 0,
    } = globalQuotaStore.data;
    return (
      <Card size="small" title={t('Registry Quota')}>
        <Row gutter={24} align="middle">
          <Col span={10}>
            <Progress percent={quotaPercent(globalQuotaStore.data)} />
          </Col>
          <Col span={4}>
            <strong>{t('Used')}</strong>
            <div>{formatSize(used)}</div>
          </Col>
          <Col span={4}>
            <strong>{t('Reserved')}</strong>
            <div>{formatSize(reserved)}</div>
          </Col>
          <Col span={6}>
            <strong>{t('Limit')}</strong>
            <div>{formatSize(limit)}</div>
          </Col>
        </Row>
      </Card>
    );
  }
}

export default observer(QuotaSummary);
