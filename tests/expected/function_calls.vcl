// Test: Function call parsing

sub vcl_recv {
  declare local var.out STRING;
  set req.http.X-Func-echo-s = "value";
  call echo;
  set req.http.X-Test = req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = "a, b";
  call echo;
  set var.out = req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = regsub(req.url.path, "/+", "/");
  call echo;
  set var.out = req.http.X-Func-echo-Return;
  set req.http.X-Func-echo-s = "a   b";
  call echo;
  set var.out = req.http.X-Func-echo-Return;
}

// Function: echo
//@recv, hash, hit, miss, pass, fetch, error, deliver, log
sub echo {

  declare local var.s STRING;

  set var.s = req.http.X-Func-echo-s;

  declare local var.return_value STRING;

  set var.return_value = var.s;

  set req.http.X-Func-echo-Return = var.return_value;
}
