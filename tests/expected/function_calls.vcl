// Test: Function call parsing



sub vcl_recv {
  declare local var.out STRING;
  set req.http.X-Func-echo-s = "value";
  call echo;
  set req.http.X-Test = req.http.X-Func-echo-Return;
  unset req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = "kept";
  call echo;
  set req.http.x-func-echo-return = req.http.X-Func-echo-Return;
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
  set req.http.X-Func-join-a = "\";
  set req.http.X-Func-join-b = "b";
  call join;
  set var.out = req.http.X-Func-join-Return;
  unset req.http.X-Func-join-Return;
  set req.http.X-Slash = "\";
  set req.http.X-Smile = ":)";
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
