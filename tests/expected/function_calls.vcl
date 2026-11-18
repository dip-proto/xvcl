// Test: Function call parsing










sub vcl_hash {
  set req.http.X-Func-echo-s = req.url;
  call echo;
  set req.hash += req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  return(hash);
}

sub vcl_recv {
  declare local var.out STRING;
  declare local var.ok BOOL;
  declare local var.n INTEGER;
  set req.http.X-Func-echo-s = "value";
  call echo;
  set req.http.X-Test = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = "x";
  call echo;
  set req.http.Control = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = "kept";
  call echo;
  set req.http.x-func-echo-return = req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = "x";
  call echo;
  set req.http.X-Label- = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = "a, b";
  call echo;
  set var.out = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = ":)";
  call echo;
  set var.out = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = regsub(req.url.path, "/+", "/");
  call echo;
  set var.out = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = "a   b";
  call echo;
  set var.out = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo_twice-s = req.url;
  call echo_twice;
  set var.out = req.http.X-Func-echo_twice-Return;
  unset req.http.X-Func-echo_twice-Return;
  set req.http.X-Func-join-a = req.http.Host;
  set req.http.X-Func-join-b = req.url;
  call join;
  set var.out = req.http.X-Func-join-Return;
  unset req.http.X-Func-join-Return;
  set req.http.X-Func-join-a = "\";
  set req.http.X-Func-join-b = "b";
  call join;
  set var.out = req.http.X-Func-join-Return;
  unset req.http.X-Func-join-Return;
  call first;
  set var.out = req.http.X-Func-first-Return;
  unset req.http.X-Func-first-Return;
  set req.http.X-Func-is_api-url = req.url;
  call is_api;
  set var.ok = (req.http.X-Func-is_api-Return == "true");
  unset req.http.X-Func-is_api-Return;
  if (var.ok) {
    set req.http.X-Func-yes_no-flag = "true";
  } else {
    set req.http.X-Func-yes_no-flag = "false";
  }
  call yes_no;
  set var.out = req.http.X-Func-yes_no-Return;
  unset req.http.X-Func-yes_no-Return;
  set req.http.X-Func-in_range-n = std.itoa(60);
  call in_range;
  set var.ok = (req.http.X-Func-in_range-Return == "true");
  unset req.http.X-Func-in_range-Return;
  set req.http.X-Slash = "\";
  set req.http.X-Smile = ":)";
  set req.http.X-Banner = {"first line
echo(not a call)"};
  set var.n = std.strlen(req.url);
}

// Function: echo
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub echo {

  declare local var.s STRING;

  set var.s = req.http.X-Func-echo-s;
  unset req.http.X-Func-echo-s;

  declare local var.return_value STRING;

  set var.return_value = var.s;
  set req.http.X-Func-echo-Return = var.return_value;
  return;
}

// Function: echo_twice
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub echo_twice {

  declare local var.s STRING;

  set var.s = req.http.X-Func-echo_twice-s;
  unset req.http.X-Func-echo_twice-s;

  declare local var.return_value STRING;

  set req.http.X-Func-echo-s = var.s;
  call echo;
  set var.return_value = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo_twice-Return = var.return_value;
  return;
}

// Function: join
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub join {

  declare local var.a STRING;
  declare local var.b STRING;

  set var.a = req.http.X-Func-join-a;
  unset req.http.X-Func-join-a;
  set var.b = req.http.X-Func-join-b;
  unset req.http.X-Func-join-b;

  declare local var.return_value STRING;

  set var.return_value = var.a + "/" + var.b;
  set req.http.X-Func-join-Return = var.return_value;
  return;
}

// Function: is_api
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub is_api {

  declare local var.url STRING;

  set var.url = req.http.X-Func-is_api-url;
  unset req.http.X-Func-is_api-url;

  declare local var.return_value BOOL;

  if (var.url == "") { return ; }
  if (var.url ~ "^/api/") { set var.return_value = true; if (var.return_value) { set req.http.X-Func-is_api-Return = "true"; } else { set req.http.X-Func-is_api-Return = "false"; } return; }
  set var.return_value = false;
  if (var.return_value) {
    set req.http.X-Func-is_api-Return = "true";
  } else {
    set req.http.X-Func-is_api-Return = "false";
  }
  return; /* everything else */
}

// Function: yes_no
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub yes_no {

  declare local var.flag BOOL;

  set var.flag = (req.http.X-Func-yes_no-flag == "true");
  unset req.http.X-Func-yes_no-flag;

  declare local var.return_value STRING;

  if (var.flag) { set var.return_value = "yes"; set req.http.X-Func-yes_no-Return = var.return_value; return; } else { set var.return_value = "no"; set req.http.X-Func-yes_no-Return = var.return_value; return; }

  set req.http.X-Func-yes_no-Return = var.return_value;
}

// Function: in_range
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub in_range {

  declare local var.n INTEGER;

  set var.n = std.atoi(req.http.X-Func-in_range-n);
  unset req.http.X-Func-in_range-n;

  declare local var.return_value BOOL;

  if (var.n > 50 && var.n < 100) { set var.return_value = true; if (var.return_value) { set req.http.X-Func-in_range-Return = "true"; } else { set req.http.X-Func-in_range-Return = "false"; } return; }
  set var.return_value = false;
  if (var.return_value) {
    set req.http.X-Func-in_range-Return = "true";
  } else {
    set req.http.X-Func-in_range-Return = "false";
  }
  return;
}

// Function: first
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub first {

  declare local var.return_value STRING;

  set var.return_value = "only";
  set req.http.X-Func-first-Return = var.return_value;
  return;
}
