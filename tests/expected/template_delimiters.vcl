// Test: Template delimiters inside Python strings and containers

sub vcl_recv {
    set req.http.X-Braces = "}}";
    set req.http.X-Dict = "}}";
    set req.http.X-List = "second";
}
