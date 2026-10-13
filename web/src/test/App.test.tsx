import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from '../App';

describe('App', () => {
  it('renders the header', () => {
    render(<App />);
    expect(screen.getByText(/MiniCoder Console/i)).toBeInTheDocument();
  });

  it('renders task input section', () => {
    render(<App />);
    expect(screen.getByText(/New Task/i)).toBeInTheDocument();
  });

  it('renders runs history section', () => {
    render(<App />);
    expect(screen.getByText(/Run History/i)).toBeInTheDocument();
  });
});
