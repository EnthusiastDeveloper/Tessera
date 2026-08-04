import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

describe('App', () => {
  it('renders the app title', () => {
    render(<App />)
    const heading = screen.getByRole('heading', { name: /tessera/i })
    expect(heading).toBeInTheDocument()
  })

  it('displays the description', () => {
    render(<App />)
    const description = screen.getByText(/self-hosted task scheduling/i)
    expect(description).toBeInTheDocument()
  })
})
