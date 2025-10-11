# xvcl Quick Reference

Quick reference for xvcl (Extended VCL compiler). See [README.md](README.md) for full documentation.

## Basic Usage

```bash
# Compile an xvcl file
xvcl input.xvcl -o output.vcl

# With include paths
xvcl input.xvcl -o output.vcl -I ./includes

# Debug mode
xvcl input.xvcl --debug
```

## Syntax Reference

### Constants

```vcl
#const NAME TYPE = value

// Examples:
#const PORT INTEGER = 8080
#const HOST STRING = "example.com"
#const ENABLED BOOL = True
#const VERSION FLOAT = 1.5
```

### Template Expressions

```vcl
{{expression}}

// Examples:
set req.http.X-Port = "{{PORT}}";
backend F_{{REGION}}_{{ENV}} { ... }
set req.http.X-Value = "{{PORT * 2}}";
```

### For Loops

```vcl
#for variable in iterable
  // code to repeat
#endfor

// Examples:
#for i in range(5)
  backend web{{i}} { ... }
#endfor

#for name in ["web1", "web2", "web3"]
  backend {{name}} { ... }
#endfor
```

### Conditionals

```vcl
#if condition
  // code when true
#else
  // code when false (optional)
#endif

// Examples:
#if PRODUCTION
  set req.http.X-Env = "prod";
#else
  set req.http.X-Env = "dev";
#endif
```

### Variables

```vcl
#let name TYPE = expression;

// Example:
#let timestamp STRING = std.time(now, now);
// Expands to:
//   declare local var.timestamp STRING;
//   set var.timestamp = std.time(now, now);
```

### File Includes

```vcl
#include "path/to/file.xvcl"

// Examples:
#include "includes/backends.xvcl"
#include "shared/security.xvcl"
```

### Inline Macros

```vcl
#inline macro_name(param1, param2, ...)
expression
#endinline

// Examples:
#inline add_prefix(s)
"prefix-" + s
#endinline

#inline cache_key(url, host)
digest.hash_md5(url + "|" + host)
#endinline

// Usage:
set req.http.X-Key = cache_key(req.url, req.http.Host);
```

### Functions

```vcl
// Single return value
#def function_name(param1 TYPE, param2 TYPE) -> RETURN_TYPE
  // function body
  return value;
#enddef

// Multiple return values (tuple)
#def function_name(param TYPE) -> (TYPE1, TYPE2)
  // function body
  return value1, value2;
#enddef

// Examples:
#def normalize(path STRING) -> STRING
  declare local var.result STRING;
  set var.result = std.tolower(path);
  return var.result;
#enddef

#def parse(input STRING) -> (STRING, STRING)
  return "part1", "part2";
#enddef

// Usage:
set var.clean = normalize("/PATH");
set var.a, var.b = parse("input");
```

## Supported Types

- `INTEGER` - Whole numbers
- `STRING` - Text strings
- `FLOAT` - Decimal numbers
- `BOOL` - True/False

## Built-in Functions (in expressions)

- `range(n)` - Number sequence 0 to n-1
- `len(list)` - List length
- `str(x)` - Convert to string
- `int(x)` - Convert to integer
- `hex(n)` - Hexadecimal
- `format(x, fmt)` - Format values
- `enumerate(iterable)` - Enumerate with indices
- `min(...)` - Minimum value
- `max(...)` - Maximum value
- `abs(n)` - Absolute value

## Command-Line Options

| Option | Description |
|--------|-------------|
| `input` | Input xvcl file (required) |
| `-o, --output` | Output VCL file |
| `-I, --include` | Add include search path (repeatable) |
| `--debug` | Enable debug mode |
| `--source-maps` | Add source map comments |
| `-v, --verbose` | Verbose output |

## Common Patterns

### Backend generation from list

```vcl
#const BACKENDS = ["web1", "web2", "web3"]

#for backend in BACKENDS
backend F_{{backend}} {
  .host = "{{backend}}.example.com";
  .port = "443";
}
#endfor
```

### Environment-specific config

```vcl
#const PRODUCTION = True

#if PRODUCTION
  #const CACHE_TTL = 3600
  #const BACKEND_HOST = "prod.example.com"
#else
  #const CACHE_TTL = 60
  #const BACKEND_HOST = "dev.example.com"
#endif
```

### Reusable string manipulation

```vcl
#inline normalize_host(host)
std.tolower(regsub(host, "^www\.", ""))
#endinline

set req.http.X-Clean-Host = normalize_host(req.http.Host);
```

### Complex reusable logic

```vcl
#def should_cache(url STRING, method STRING) -> BOOL
  if (method != "GET" && method != "HEAD") {
    return false;
  }
  if (url ~ "^/api/") {
    return false;
  }
  return true;
#enddef

set var.cacheable = should_cache(req.url, req.request);
```

## Macros vs Functions

| Use Case | Use This |
|----------|----------|
| Simple expression | Macro |
| String concatenation | Macro |
| Complex logic | Function |
| Multiple statements | Function |
| Multiple return values | Function |
| Zero overhead needed | Macro |

## Error Messages

Common errors and solutions:

| Error | Solution |
|-------|----------|
| Name 'X' is not defined | Check constant/variable spelling |
| Invalid #const syntax | Use: `#const NAME TYPE = value` |
| No matching #endfor | Add closing `#endfor` |
| Circular include detected | Restructure includes |
| Cannot find included file | Check path, use `-I` flag |

## Workflow

```bash
# 1. Write xvcl file
vim main.xvcl

# 2. Compile
xvcl main.xvcl -o main.vcl

# 3. Validate with Falco
falco lint main.vcl

# 4. Test
falco test main.vcl

# 5. Deploy
# (upload main.vcl to Fastly)
```

## Tips

- Use `.xvcl` extension for xvcl files
- Keep constants at the top of files
- Comment your macros and functions
- Use `--debug` when troubleshooting
- Validate generated VCL with Falco
- Version control both xvcl files and output (or just xvcl files)

---

For detailed documentation with examples, see [README.md](README.md).
