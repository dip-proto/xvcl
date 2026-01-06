// Test: Template expressions with Python functions

// hex conversion
set req.http.X-Hex = "0x1f90";
set req.http.X-Hex2 = "0xff";

// format function
set req.http.X-Padded = "00042";
set req.http.X-Float = "3.14";

// len function
set req.http.X-Count = "4";
set req.http.X-Names = "3";

// min/max functions
set req.http.X-Min = "10";
set req.http.X-Max = "40";
set req.http.X-MinDirect = "3";
set req.http.X-MaxDirect = "9";

// abs function
set req.http.X-Abs = "42";
set req.http.X-AbsPos = "42";

// int/str conversions
set req.http.X-Int = "42";
set req.http.X-Str = "123";

// arithmetic expressions
set req.http.X-Add = "13";
set req.http.X-Sub = "7";
set req.http.X-Mul = "30";
set req.http.X-Div = "3";
set req.http.X-Mod = "1";

// boolean expressions
set req.http.X-And = "False";
set req.http.X-Or = "True";
set req.http.X-Not = "False";

// string operations
set req.http.X-Concat = "api-v2";
