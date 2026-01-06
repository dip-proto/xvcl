// Test: For loops with range and lists

// Basic for loop with list
backend web1 { }
backend web2 { }
backend web3 { }

// For loop with range
set req.http.X-Index-0 = "0";
set req.http.X-Index-1 = "1";
set req.http.X-Index-2 = "2";

// For loop with range(start, end)
set req.http.X-Range-5 = "value";
set req.http.X-Range-6 = "value";
set req.http.X-Range-7 = "value";

// For loop with enumerate
set req.http.X-Server-0 = "web1";
set req.http.X-Server-1 = "web2";
set req.http.X-Server-2 = "web3";
