import { quotaPercent } from './QuotaSummary';

describe('Registry quota summary', () => {
  it('uses current usage without adding reservations twice', () => {
    expect(
      quotaPercent({
        limit_bytes: 100,
        used_bytes: 25,
        reserved_bytes: 10,
      })
    ).toBe(25);
  });

  it('bounds the progress value and handles an empty limit', () => {
    expect(quotaPercent({ limit_bytes: 10, used_bytes: 15 })).toBe(100);
    expect(quotaPercent({ limit_bytes: 0, used_bytes: 15 })).toBe(0);
    expect(quotaPercent({})).toBe(0);
  });
});
