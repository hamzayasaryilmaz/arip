// Package state holds the in-memory order state for the payment service.
// In a real system this would be backed by Postgres; for the Phase 1 demo
// it is intentionally simple so that failure scenarios are easy to read.
package state

import (
	"sync"
	"time"
)

// StateChange records one transition in an order's lifecycle. The
// trace_id is captured so that downstream tooling (the telemetry
// correlator in Phase 3) can join state history with traces.
type StateChange struct {
	At      time.Time `json:"at"`
	Status  string    `json:"status"`
	TraceID string    `json:"trace_id"`
	Note    string    `json:"note,omitempty"`
}

// Order is the materialised state of an order.
type Order struct {
	ID      string        `json:"id"`
	SKU     string        `json:"sku"`
	Status  string        `json:"status"`
	History []StateChange `json:"history"`
}

// Store is a goroutine-safe in-memory order store.
type Store struct {
	mu     sync.Mutex
	orders map[string]*Order
}

// NewStore constructs an empty Store.
func NewStore() *Store {
	return &Store{orders: make(map[string]*Order)}
}

// Get returns a copy of the order with the given id, or false if absent.
func (s *Store) Get(id string) (*Order, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	o, ok := s.orders[id]
	if !ok {
		return nil, false
	}
	cp := *o
	cp.History = append([]StateChange{}, o.History...)
	return &cp, true
}

// Transition updates the order's status and appends a history entry.
// It returns the previous status so callers can detect out-of-order
// transitions (for example, a webhook arriving before /checkout has
// finished reserving inventory).
func (s *Store) Transition(id, sku, newStatus, traceID, note string) (prev string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	o, ok := s.orders[id]
	if !ok {
		o = &Order{ID: id, SKU: sku}
		s.orders[id] = o
	}
	prev = o.Status
	o.Status = newStatus
	if sku != "" {
		o.SKU = sku
	}
	o.History = append(o.History, StateChange{
		At:      time.Now().UTC(),
		Status:  newStatus,
		TraceID: traceID,
		Note:    note,
	})
	return prev
}
