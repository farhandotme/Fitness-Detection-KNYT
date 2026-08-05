import React from 'react';
import { Link } from 'wouter';

export default function NotFound() {
  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-background text-foreground">
      <div className="text-center p-8 bg-card rounded-xl border border-border">
        <h1 className="text-6xl font-bold mb-4">404</h1>
        <p className="text-xl text-muted-foreground mb-8">Page not found</p>
        <Link href="/" className="bg-primary text-primary-foreground px-6 py-3 rounded-lg font-semibold hover:brightness-110">
          Return Home
        </Link>
      </div>
    </div>
  );
}