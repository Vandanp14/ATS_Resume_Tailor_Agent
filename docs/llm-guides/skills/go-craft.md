<!-- Source: vandan-llm-toolkit skills/go-craft/SKILL.md — re-run install.sh codex to refresh, don't hand-edit. -->


# Go Craft

Go's standard library and language absorb ideas on a six-month cadence, and each release retires an idiom that a weak model still emits confidently from training data: `interface{}`, `rand.Seed`, `github.com/pkg/errors`, a hand-rolled router. The code compiles and looks fluent — it is just a version or two out of date. This skill is not a Go tutorial. It is a discipline for producing code that matches the release actually installed, by mapping each stale pattern to its current replacement and refusing the ones that are now defects.

## Step 1 — Version lock first

Resolve the installed Go major before applying anything below. Run `go version`, read the `go` directive in `go.mod`, and follow the **version-grounded-coding** skill's procedure (resolve, record a version-lock header, verify against the version's own docs). Do not write dependent code from memory. Everything below is written for the current release line; if the installed major is older, downgrade the specific recipe (e.g. no `net/http` method routing before 1.22, no `math/rand/v2` before 1.22, no `synctest.Test` before 1.25) and say so.

## Step 2 — The idiom table

The core artifact. Each row is one stale pattern a weak model emits and its current, copy-paste replacement. Apply every row that appears in the code.

| Stale way (from training data) | Current way |
|---|---|
| `var x interface{}` | `var x any` (alias since 1.18) |
| `golang.org/x/exp/constraints.Ordered` | `cmp.Ordered` (stdlib, 1.21+) |
| `rand.Seed(...)` + `math/rand` | `math/rand/v2`: `rand.IntN(100)`, `rand.N(n)`, `rand.Shuffle` — auto-seeded, no `Seed` call |
| `github.com/pkg/errors` `.Wrap` | `fmt.Errorf("loading %d: %w", id, err)` |
| `golang.org/x/exp/slog` or zap-by-default | stdlib `log/slog`: `slog.New(slog.NewJSONHandler(os.Stdout, nil))` |
| `gorilla/mux` / `chi` for basic REST | stdlib mux: `mux.HandleFunc("GET /tasks/{id}", h)`, `r.PathValue("id")` (1.22+) |
| `v := v` loop-var copy before a goroutine | not needed — per-iteration loop vars since 1.22 |
| manual `for i := 0; i < len(s); i++` when consuming a sequence | `for v := range seq` with `iter.Seq[V]`; `slices.Collect`, `maps.Keys` |
| interning strings via a hand-rolled `map[string]string` | `unique.Make(s)` → `unique.Handle[T]` (1.23+) |
| `err.Error() == "not found"` string compare | sentinel `var ErrNotFound = errors.New(...)` + `errors.Is(err, ErrNotFound)` |
| `tools.go` with blank imports | `tool` directives in `go.mod` (1.24+) |
| `http.ListenAndServe(addr, mux)` in production | `&http.Server{Addr, Handler, ReadTimeout, WriteTimeout}` |
| `context.Context` stored in a struct field | pass `ctx context.Context` as the first parameter |

Read [references/layout-and-errors.md](references/layout-and-errors.md) before deciding package structure or writing any error path. Read [references/concurrency-and-http.md](references/concurrency-and-http.md) before spawning a goroutine, writing an HTTP server, choosing a dependency over the stdlib, or reaching for generics.

## Step 3 — Failure catalog

These are defects, not style choices. Fix on sight.

- **Ignored error returns.** Never `_ =` or drop an `error`. Handle it, wrap it with `%w`, or return it. `errcheck` (in the config below) fails the build on this.
- **Interface pollution.** Accept interfaces, return structs. Do not define an interface next to the one struct that implements it "for testing" — define it at the consumer that needs the abstraction, and only once a second implementation exists.
- **Goroutine leaks.** Every `go` needs an owner, a `context`, and a way to stop. A goroutine that blocks on a channel with no `ctx.Done()` case leaks. See the concurrency reference.
- **`init()` magic and package-level mutable state.** Prefer explicit constructors (`func New(deps Deps) *Service`) and wiring in `main`. `init()` hides ordering and defeats tests; global singletons make behavior untestable.
- **Empty-interface / stringly-typed APIs.** `any` in a signature is a smell — use a concrete type or a generic type parameter. Reserve `any` for genuinely heterogeneous data (JSON, logging fields).
- **`panic` for ordinary errors.** Return `error` values. Never panic in a library; reserve panic for unrecoverable programmer bugs (e.g. a violated invariant that cannot happen).

## Step 4 — Canonical config

Copy verbatim. Adjust the `go` line to the resolved major.

```
# go.mod
go 1.26
tool golang.org/x/tools/cmd/goimports   // Go 1.24+ tool directive
```

```sh
gofmt -l -w .          # non-negotiable; -l lists, -w writes
goimports -w .         # import management on top of gofmt
go vet ./...           # also runs inside `go test`
golangci-lint run      # de-facto meta-linter (v2 line)
golangci-lint migrate  # converts a v1 .golangci.yml to v2
```

```yaml
# .golangci.yml  (v2 schema)
version: "2"
linters:
  default: standard
  enable: [errcheck, govet, staticcheck]
```

## Step 5 — Testing conventions

Table-driven tests with `t.Run` subtests and `t.Parallel()` are the default. Loop-var capture is safe since 1.22, so no per-iteration copy is needed. Use `t.Cleanup` for teardown and `t.Context()` (1.24+) for a test-scoped context. Native fuzzing (`func FuzzX(f *testing.F)`) is stable stdlib. For concurrent/time-dependent tests use `testing/synctest` — `synctest.Test(t, func(t *testing.T){ ... })` (GA in 1.25; the older `synctest.Run` is deprecated). `testify` is a fine pragmatic default for assert/require/mock, but stdlib-only with small generic helpers is equally idiomatic — match the codebase.

```go
for _, tt := range tests {
    t.Run(tt.name, func(t *testing.T) {
        t.Parallel()
        got := Fn(tt.in)
        if got != tt.want {
            t.Errorf("Fn(%v) = %v, want %v", tt.in, got, tt.want)
        }
    })
}
```

## Closing gate

Do not report Go code as done until every box holds:

- [ ] Ran the version-lock step; recipes match the installed major.
- [ ] No `interface{}`, no `pkg/errors`, no `rand.Seed`, no `x/exp/slog`, no hand-rolled router where stdlib suffices.
- [ ] Every error is wrapped with `%w` or deliberately `%v`; sentinels checked via `errors.Is`, typed errors via `errors.As`.
- [ ] No ignored error returns; no `panic` for ordinary failures.
- [ ] Every goroutine has an owner, a context, and a stop path.
- [ ] `gofmt`, `goimports`, `go vet ./...`, and `golangci-lint run` are clean.
- [ ] Tests are table-driven with `t.Parallel()` where safe.
