// Test: Include-once semantics (file included twice, should only appear once)
// Shared constants


// Repeating an include under #if is fine when the first one wasn't conditional
// Backend definitions

backend F_origin1 {
    .host = "origin1.example.com";
    .port = "443";
}
backend F_origin2 {
    .host = "origin2.example.com";
    .port = "443";
}


// A file without VCL may be included again, even under #if
/*
Notes only, so including this file twice is harmless.
*/


// Should still only have one definition of constants
set req.http.X-Port = "8080";
