import '@testing-library/jest-dom';

(globalThis as {ResizeObserver?: typeof ResizeObserver}).ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};
