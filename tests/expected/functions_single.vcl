// Test: Functions with single return value




sub vcl_recv {
    declare local var.sum INTEGER;
    set req.http.X-Func-add-a = std.itoa(5);
    set req.http.X-Func-add-b = std.itoa(10);
    call add;
    set var.sum = std.atoi(req.http.X-Func-add-Return);

    declare local var.str STRING;
    set req.http.X-Func-concat-s1 = "hello";
    set req.http.X-Func-concat-s2 = "world";
    call concat;
    set var.str = req.http.X-Func-concat-Return;

    declare local var.doubled FLOAT;
    set req.http.X-Func-double_float-x = "" + 3.5;
    call double_float;
    set var.doubled = std.atof(req.http.X-Func-double_float-Return);

    declare local var.positive BOOL;
    set req.http.X-Func-is_positive-n = std.itoa(42);
    call is_positive;
    set var.positive = (req.http.X-Func-is_positive-Return == "true");
}

// Function: add
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub add {

  declare local var.a INTEGER;
  declare local var.b INTEGER;

  set var.a = std.atoi(req.http.X-Func-add-a);
  set var.b = std.atoi(req.http.X-Func-add-b);

  declare local var.return_value INTEGER;

    declare local var.sum INTEGER;
    set var.sum = var.a + var.b;
    set var.return_value = var.sum;

  set req.http.X-Func-add-Return = std.itoa(var.return_value);
}

// Function: concat
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub concat {

  declare local var.s1 STRING;
  declare local var.s2 STRING;

  set var.s1 = req.http.X-Func-concat-s1;
  set var.s2 = req.http.X-Func-concat-s2;

  declare local var.return_value STRING;

    declare local var.result STRING;
    set var.result = var.s1 + var.s2;
    set var.return_value = var.result;

  set req.http.X-Func-concat-Return = var.return_value;
}

// Function: double_float
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub double_float {

  declare local var.x FLOAT;

  set var.x = std.atof(req.http.X-Func-double_float-x);

  declare local var.return_value FLOAT;

    declare local var.result FLOAT;
    set var.result = var.x * 2.0;
    set var.return_value = var.result;

  set req.http.X-Func-double_float-Return = "" + var.return_value;
}

// Function: is_positive
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub is_positive {

  declare local var.n INTEGER;

  set var.n = std.atoi(req.http.X-Func-is_positive-n);

  declare local var.return_value BOOL;

    declare local var.result BOOL;
    if (var.n > 0) {
        set var.result = true;
    } else {
        set var.result = false;
    }
    set var.return_value = var.result;

  if (var.return_value) {
    set req.http.X-Func-is_positive-Return = "true";
  } else {
    set req.http.X-Func-is_positive-Return = "false";
  }
}
