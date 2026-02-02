// Test: Functions with tuple return values



sub vcl_recv {
    declare local var.q INTEGER;
    declare local var.r INTEGER;
    set req.http.X-Func-divmod-a = std.itoa(17);
    set req.http.X-Func-divmod-b = std.itoa(5);
    call divmod;
    set var.q = std.atoi(req.http.X-Func-divmod-Return0);
    set var.r = std.atoi(req.http.X-Func-divmod-Return1);

    declare local var.key STRING;
    declare local var.value STRING;
    set req.http.X-Func-parse_pair-s = "name:john";
    call parse_pair;
    set var.key = req.http.X-Func-parse_pair-Return0;
    set var.value = req.http.X-Func-parse_pair-Return1;

    declare local var.min INTEGER;
    declare local var.max INTEGER;
    declare local var.sum INTEGER;
    set req.http.X-Func-get_stats-a = std.itoa(10);
    set req.http.X-Func-get_stats-b = std.itoa(5);
    set req.http.X-Func-get_stats-c = std.itoa(20);
    call get_stats;
    set var.min = std.atoi(req.http.X-Func-get_stats-Return0);
    set var.max = std.atoi(req.http.X-Func-get_stats-Return1);
    set var.sum = std.atoi(req.http.X-Func-get_stats-Return2);
}

// Function: divmod
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub divmod {

  declare local var.a INTEGER;
  declare local var.b INTEGER;

  set var.a = std.atoi(req.http.X-Func-divmod-a);
  set var.b = std.atoi(req.http.X-Func-divmod-b);

  declare local var.return_value0 INTEGER;
  declare local var.return_value1 INTEGER;

    declare local var.quotient INTEGER;
    declare local var.remainder INTEGER;
    set var.quotient = var.a / var.b;
    set var.remainder = var.a % var.b;
    set var.return_value0 = var.quotient;
    set var.return_value1 = var.remainder;

  set req.http.X-Func-divmod-Return0 = std.itoa(var.return_value0);
  set req.http.X-Func-divmod-Return1 = std.itoa(var.return_value1);
}

// Function: parse_pair
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub parse_pair {

  declare local var.s STRING;

  set var.s = req.http.X-Func-parse_pair-s;

  declare local var.return_value0 STRING;
  declare local var.return_value1 STRING;

    declare local var.key STRING;
    declare local var.value STRING;
    set var.key = regsub(var.s, ":.*", "");
    set var.value = regsub(var.s, "^[^:]*:", "");
    set var.return_value0 = var.key;
    set var.return_value1 = var.value;

  set req.http.X-Func-parse_pair-Return0 = var.return_value0;
  set req.http.X-Func-parse_pair-Return1 = var.return_value1;
}

// Function: get_stats
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub get_stats {

  declare local var.a INTEGER;
  declare local var.b INTEGER;
  declare local var.c INTEGER;

  set var.a = std.atoi(req.http.X-Func-get_stats-a);
  set var.b = std.atoi(req.http.X-Func-get_stats-b);
  set var.c = std.atoi(req.http.X-Func-get_stats-c);

  declare local var.return_value0 INTEGER;
  declare local var.return_value1 INTEGER;
  declare local var.return_value2 INTEGER;

    declare local var.min INTEGER;
    declare local var.max INTEGER;
    declare local var.sum INTEGER;
    if (var.a < var.b && var.a < var.c) {
        set var.min = var.a;
    } else if (var.b < var.c) {
        set var.min = var.b;
    } else {
        set var.min = var.c;
    }
    if (var.a > var.b && var.a > var.c) {
        set var.max = var.a;
    } else if (var.b > var.c) {
        set var.max = var.b;
    } else {
        set var.max = var.c;
    }
    set var.sum = var.a + var.b + var.c;
    set var.return_value0 = var.min;
    set var.return_value1 = var.max;
    set var.return_value2 = var.sum;

  set req.http.X-Func-get_stats-Return0 = std.itoa(var.return_value0);
  set req.http.X-Func-get_stats-Return1 = std.itoa(var.return_value1);
  set req.http.X-Func-get_stats-Return2 = std.itoa(var.return_value2);
}
