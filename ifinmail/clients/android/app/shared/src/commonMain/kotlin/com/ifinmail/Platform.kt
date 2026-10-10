package com.ifinmail

interface Platform {
    val name: String
}

expect fun getPlatform(): Platform